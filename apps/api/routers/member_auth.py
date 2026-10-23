"""Phone-based member registration and login using a hosted SMS verifier."""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.membership_models import User
from apps.api.ratelimit import SlidingWindowLimiter, rate_limit

router = APIRouter(prefix="/auth/member", tags=["member-auth"])
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
_sms_send_limiter = SlidingWindowLimiter(3, window=60)
_sms_ip_limiter = SlidingWindowLimiter(5, window=60)
_sms_verify_limiter = SlidingWindowLimiter(10, window=60)


class OtpStart(BaseModel):
    phone: str = Field(min_length=9, max_length=16)
    intent: str = Field(pattern="^(register|login)$")


class OtpVerify(BaseModel):
    phone: str = Field(min_length=9, max_length=16)
    code: str = Field(pattern="^[0-9]{4,10}$")
    intent: str = Field(pattern="^(register|login)$")


def _phone(value: str) -> str:
    phone = value.strip()
    if not E164.fullmatch(phone):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="手机号请使用国际格式，例如 +61412345678",
        )
    return phone


def _twilio_settings() -> tuple[str, str, str]:
    settings = get_settings()
    if (
        settings.sms_provider.lower() != "twilio"
        or not settings.twilio_account_sid
        or not settings.twilio_auth_token
        or not settings.twilio_verify_service_sid
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="手机号验证尚未启用，请先配置短信服务",
        )
    return (
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_verify_service_sid,
    )


async def _twilio_request(path: str, data: dict[str, str]) -> dict:
    account_sid, auth_token, service_sid = _twilio_settings()
    url = (
        "https://verify.twilio.com/v2/Services/"
        f"{service_sid}/{path}"
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                url,
                data=data,
                auth=(account_sid, auth_token),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="短信服务暂时无法连接，请稍后重试",
        ) from exc
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="短信服务暂时不可用")
    if response.status_code >= 400:
        # Avoid forwarding provider response details, which can include phone data.
        raise HTTPException(status_code=400, detail="短信验证码请求未通过，请检查手机号或验证码")
    return response.json()


@router.post("/otp/start", dependencies=[Depends(rate_limit("member-otp-start"))])
async def start_otp(
    payload: OtpStart,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    phone = _phone(payload.phone)
    client_ip = request.client.host if request.client else "unknown"
    if not _sms_send_limiter.allow(phone) or not _sms_ip_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="验证码发送过于频繁，请稍后再试")
    existing = db.scalar(select(User).where(User.phone_e164 == phone))
    if payload.intent == "register" and existing is not None:
        raise HTTPException(status_code=409, detail="该手机号已经注册，请直接登录")
    if payload.intent == "login" and (existing is None or not existing.is_active):
        raise HTTPException(status_code=404, detail="该手机号尚未注册")
    result = await _twilio_request("Verifications", {"To": phone, "Channel": "sms"})
    if result.get("status") not in {"pending", "approved"}:
        raise HTTPException(status_code=502, detail="短信服务未能发送验证码")
    return {"status": "sent", "message": "验证码已发送"}


@router.post("/otp/verify", dependencies=[Depends(rate_limit("member-otp-verify"))])
async def verify_otp(
    payload: OtpVerify,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    phone = _phone(payload.phone)
    client_ip = request.client.host if request.client else "unknown"
    if not _sms_verify_limiter.allow(f"{client_ip}:{phone}"):
        raise HTTPException(status_code=429, detail="验证码尝试过于频繁，请稍后再试")
    result = await _twilio_request(
        "VerificationCheck", {"To": phone, "Code": payload.code}
    )
    if result.get("status") != "approved":
        raise HTTPException(status_code=401, detail="验证码错误或已过期")

    user = db.scalar(select(User).where(User.phone_e164 == phone))
    if payload.intent == "register":
        if user is not None:
            raise HTTPException(status_code=409, detail="该手机号已经注册，请直接登录")
        user = User(phone_e164=phone, phone_verified=True, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="该手机号尚未注册")
    else:
        user.phone_verified = True
        db.commit()

    return {"status": "ok", "member": {"id": user.id, "phone": user.phone_e164}}
