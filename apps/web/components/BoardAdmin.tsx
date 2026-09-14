"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { createBoard, discoverBoards, type BoardCandidate } from "@/lib/api";

const PROVIDERS = [
  "greenhouse",
  "lever",
  "ashby",
  "workable",
  "smartrecruiters",
  "recruitee",
  "breezy",
  "workday",
  "personio",
  "teamtailor",
  "bamboohr",
  "jazzhr",
  "pinpoint",
  "rippling",
  "jobvite",
];

export function BoardAdmin() {
  const router = useRouter();
  const [domain, setDomain] = useState("");
  const [provider, setProvider] = useState("greenhouse");
  const [token, setToken] = useState("");
  const [candidates, setCandidates] = useState<BoardCandidate[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onDiscover(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    setCandidates(null);
    try {
      const found = await discoverBoards(domain.trim(), false);
      setCandidates(found);
      if (found.length === 0) setMessage("未发现已知 ATS 标识，请手动添加。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发现失败");
    } finally {
      setBusy(false);
    }
  }

  async function onAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const board = await createBoard({
        provider,
        board_token: token.trim(),
        verify: true,
      });
      setMessage(
        `已添加 ${board.provider}/${board.board_token}，当前岗位数 ${board.last_job_count}`
      );
      setToken("");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加失败");
    } finally {
      setBusy(false);
    }
  }

  async function onAddCandidate(candidate: BoardCandidate) {
    setBusy(true);
    try {
      await createBoard({
        provider: candidate.provider,
        board_token: candidate.board_token,
        verify: true,
      });
      setMessage(`已添加 ${candidate.provider}/${candidate.board_token}`);
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="job-card" style={{ marginBottom: 18 }}>
      <div className="job-card-head">
        <h2>添加 / 发现公司看板</h2>
      </div>

      <form className="match-form" onSubmit={onDiscover} style={{ margin: "8px 0" }}>
        <div className="field field-grow">
          <label htmlFor="discover-domain">公司域名</label>
          <input
            id="discover-domain"
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
            placeholder="例如 stripe.com"
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || !domain.trim()}>
            自动发现
          </button>
        </div>
      </form>

      {candidates && candidates.length > 0 ? (
        <ul className="bars">
          {candidates.map((candidate) => (
            <li key={`${candidate.provider}:${candidate.board_token}`}>
              <span>
                {candidate.provider} / {candidate.board_token}
                {candidate.verified ? ` · ${candidate.job_count} 个岗位` : " · 未通过校验"}
              </span>
              <button
                type="button"
                className="btn-ghost small"
                disabled={busy || !candidate.verified}
                onClick={() => onAddCandidate(candidate)}
              >
                添加
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <form className="match-form" onSubmit={onAdd} style={{ margin: "8px 0" }}>
        <div className="field">
          <label htmlFor="board-provider">来源</label>
          <select
            id="board-provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            {PROVIDERS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="field field-grow">
          <label htmlFor="board-token">Board token / 标识</label>
          <input
            id="board-token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="例如 stripe"
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || !token.trim()}>
            添加并校验
          </button>
        </div>
      </form>

      {message ? <p className="form-message ok">{message}</p> : null}
      {error ? <p className="form-message error">{error}</p> : null}
    </div>
  );
}
