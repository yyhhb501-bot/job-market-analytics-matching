"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import styles from "./CollectorDashboard.module.css";

type Platform = "linkedin" | "seek";
type BridgeAction = "status" | "start" | "pause" | "resume" | "sync" | "configure";

interface BridgeConfig {
  apiUrl?: string;
  deviceToken?: string;
}

interface BridgeStatusValue {
  platform: Platform;
  status: "idle" | "running" | "waiting" | "retrying" | "paused" | "done";
  message: string;
  collected: number;
  pendingSync: number;
  synced: number;
  rejectedSync?: number;
  syncError?: string | null;
  lastSyncAt: string | null;
  nextRunAt: number | null;
  needsSetup: boolean;
  canResume: boolean;
  requiresHuman: boolean;
  updatedAt: string | null;
  page: number;
  dailyTarget?: number;
  todayCollected?: number;
}

interface BridgeRequestMessage {
  type: "JOBAGG_COLLECTOR_REQUEST";
  requestId: string;
  platform: Platform;
  action: BridgeAction;
  config?: BridgeConfig;
}

interface BridgeResponseMessage {
  type: "JOBAGG_COLLECTOR_RESPONSE";
  requestId: string;
  platform: Platform;
  ok: boolean;
  value?: BridgeStatusValue;
  error?: string;
}

interface PlatformState {
  connection: "checking" | "connected" | "offline";
  data: BridgeStatusValue | null;
  error: string | null;
  busy: boolean;
}

const BRIDGE_TIMEOUT_MS = 3500;
const AUTO_POLL_INTERVAL_MS = 8000;

function formatShanghaiTime(timestamp: number | string | null | undefined): string {
  if (timestamp === null || timestamp === undefined || timestamp === "") return "—";
  const date = typeof timestamp === "number" ? new Date(timestamp) : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function statusBadgeInfo(connection: PlatformState["connection"], data: BridgeStatusValue | null) {
  if (connection === "checking") {
    return { text: "检测连接中…", className: styles.statusChecking };
  }
  if (connection === "offline" || !data) {
    return { text: "未连接", className: styles.statusOffline };
  }
  switch (data.status) {
    case "running":
      return { text: "运行中", className: styles.statusRunning };
    case "waiting":
      return { text: "等待中", className: styles.statusWaiting };
    case "retrying":
      return { text: "重试中", className: styles.statusRetrying };
    case "paused":
      return { text: "已暂停", className: styles.statusPaused };
    case "done":
      return { text: "已完成", className: styles.statusDone };
    case "idle":
    default:
      return { text: "空闲", className: styles.statusIdle };
  }
}

export function CollectorDashboard({ seekDailyTarget }: { seekDailyTarget?: number } = {}) {
  const [sources, setSources] = useState<Record<Platform, PlatformState>>({
    linkedin: { connection: "checking", data: null, error: null, busy: false },
    seek: { connection: "checking", data: null, error: null, busy: false },
  });
  const [globalMessage, setGlobalMessage] = useState<{ type: "info" | "warning" | "error"; text: string } | null>(null);
  const [isStartingAll, setIsStartingAll] = useState(false);
  const [isPausingAll, setIsPausingAll] = useState(false);
  const [pollCount, setPollCount] = useState(0);

  const mountedRef = useRef(true);
  const isStartingAllRef = useRef(false);
  const busyRef = useRef(new Set<Platform>());
  const pollingRef = useRef(false);
  const pendingRef = useRef(new Set<() => void>());

  useEffect(() => {
    mountedRef.current = true;
    const pending = pendingRef.current;
    return () => {
      mountedRef.current = false;
      for (const cancel of pending) cancel();
    };
  }, []);

  const sendBridgeMessage = useCallback((platform: Platform, action: BridgeAction, config?: BridgeConfig): Promise<BridgeStatusValue> => {
    return new Promise((resolve, reject) => {
      if (typeof window === "undefined") {
        reject(new Error("仅在客户端环境中执行"));
        return;
      }

      const requestId = typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : "req-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);

      let timer: ReturnType<typeof setTimeout> | null = null;

      const handler = (event: MessageEvent) => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        const msg = event.data as BridgeResponseMessage;
        if (!msg || msg.type !== "JOBAGG_COLLECTOR_RESPONSE") return;
        if (msg.requestId !== requestId || msg.platform !== platform) return;

        cleanup();
        if (msg.ok && msg.value) {
          resolve(msg.value);
        } else {
          reject(new Error(msg.error || "扩展未响应，请重新加载扩展后刷新本页。"));
        }
      };

      const cleanup = () => {
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        window.removeEventListener("message", handler);
        pendingRef.current.delete(cancel);
      };

      const cancel = () => { cleanup(); reject(new Error("页面已关闭")); };
      pendingRef.current.add(cancel);

      window.addEventListener("message", handler);

      timer = setTimeout(() => {
        cleanup();
        const loaded = document.documentElement.getAttribute(`data-jobagg-${platform}-bridge`);
        reject(new Error(loaded
          ? `扩展 ${loaded} 已进入本页，但后台未响应，请重新加载扩展后刷新。`
          : "未检测到扩展连接，请允许扩展在此本机网站运行，然后刷新本页。"));
      }, action === "status" ? BRIDGE_TIMEOUT_MS : 15000);

      const payload: BridgeRequestMessage = {
        type: "JOBAGG_COLLECTOR_REQUEST",
        requestId,
        platform,
        action,
        ...(config ? { config } : {}),
      };

      window.postMessage(payload, window.location.origin);
    });
  }, []);

  const requestSetup = useCallback(async (platform: Platform): Promise<BridgeConfig> => {
    const res = await fetch("/api/collector/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = "入库服务连接失败";
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        // use fallback detail
      }
      throw new Error(`设备配置失败: ${detail}`);
    }
    const data = await res.json();
    if (!data.apiUrl || !data.deviceToken) {
      throw new Error("服务端返回的设备配置无效。");
    }
    return { apiUrl: data.apiUrl, deviceToken: data.deviceToken };
  }, []);

  const refreshPlatform = useCallback(async (platform: Platform): Promise<BridgeStatusValue | null> => {
    try {
      const value = await sendBridgeMessage(platform, "status");
      if (mountedRef.current) {
        setSources((prev) => ({
          ...prev,
          [platform]: {
            connection: "connected",
            data: value,
            error: null,
            busy: prev[platform].busy,
          },
        }));
      }
      return value;
    } catch (err) {
      if (mountedRef.current) {
        const errMsg = err instanceof Error ? err.message : "连接失败";
        setSources((prev) => ({
          ...prev,
          [platform]: {
            connection: "offline",
            data: null,
            error: errMsg,
            busy: prev[platform].busy,
          },
        }));
      }
      return null;
    }
  }, [sendBridgeMessage]);

  const pollAll = useCallback(async () => {
    if (!mountedRef.current || pollingRef.current) return;
    pollingRef.current = true;
    try {
      await Promise.allSettled((["linkedin", "seek"] as Platform[])
        .filter(platform => !busyRef.current.has(platform)).map(refreshPlatform));
    } finally { pollingRef.current = false; }
    if (mountedRef.current) {
      setPollCount((c) => c + 1);
    }
  }, [refreshPlatform]);

  useEffect(() => {
    pollAll();
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") {
        pollAll();
      }
    }, AUTO_POLL_INTERVAL_MS);

    return () => {
      clearInterval(interval);
    };
  }, [pollAll]);

  const runStartForPlatform = async (platform: Platform): Promise<{ ok: boolean; message: string }> => {
    let currentStatus = sources[platform].data;
    if (!currentStatus || sources[platform].connection !== "connected") {
      currentStatus = await refreshPlatform(platform);
    }

    if (!currentStatus) {
      return { ok: false, message: "扩展未响应，请先重新加载该扩展并刷新页面" };
    }

    if (currentStatus.requiresHuman) {
      return { ok: false, message: "处于安全验证或频率限制中，请处理后点击【验证后继续】" };
    }

    if (currentStatus.needsSetup) {
      const config = await requestSetup(platform);
      try {
        await sendBridgeMessage(platform, "configure", config);
      } finally {
        config.deviceToken = undefined;
      }
    }

    const updated = await sendBridgeMessage(platform, "start");
    if (mountedRef.current) {
      setSources((prev) => ({
        ...prev,
        [platform]: { connection: "connected", data: updated, error: null, busy: false },
      }));
    }
    return { ok: true, message: "采集已启动" };
  };

  const handleStartAll = async () => {
    if (isStartingAllRef.current || isStartingAll || busyRef.current.size) return;
    isStartingAllRef.current = true;
    busyRef.current.add("linkedin"); busyRef.current.add("seek");
    setIsStartingAll(true);
    setGlobalMessage(null);

    setSources((prev) => ({
      linkedin: { ...prev.linkedin, busy: true, error: null },
      seek: { ...prev.seek, busy: true, error: null },
    }));

    try {
      const [liRes, seekRes] = await Promise.allSettled([
        runStartForPlatform("linkedin"),
        runStartForPlatform("seek"),
      ]);
      if (!mountedRef.current) return;

      const messages: string[] = [];
      let anyFailed = false;

      if (liRes.status === "fulfilled") {
        if (!liRes.value.ok) {
          anyFailed = true;
          messages.push(`领英: ${liRes.value.message}`);
          setSources((prev) => ({ ...prev, linkedin: { ...prev.linkedin, error: liRes.value.message } }));
        }
      } else {
        anyFailed = true;
        const msg = liRes.reason instanceof Error ? liRes.reason.message : "启动失败";
        messages.push(`领英: ${msg}`);
        setSources((prev) => ({ ...prev, linkedin: { ...prev.linkedin, error: msg } }));
      }

      if (seekRes.status === "fulfilled") {
        if (!seekRes.value.ok) {
          anyFailed = true;
          messages.push(`SEEK: ${seekRes.value.message}`);
          setSources((prev) => ({ ...prev, seek: { ...prev.seek, error: seekRes.value.message } }));
        }
      } else {
        anyFailed = true;
        const msg = seekRes.reason instanceof Error ? seekRes.reason.message : "启动失败";
        messages.push(`SEEK: ${msg}`);
        setSources((prev) => ({ ...prev, seek: { ...prev.seek, error: msg } }));
      }

      if (anyFailed) {
        setGlobalMessage({
          type: "warning",
          text: `部分来源未启动成功: ${messages.join("；")}`,
        });
      } else {
        setGlobalMessage({
          type: "info",
          text: "两个来源已确认启动指令，请以各自状态和入库计数为准。",
        });
      }
    } finally {
      busyRef.current.clear();
      isStartingAllRef.current = false;
      if (mountedRef.current) {
        setSources((prev) => ({
          linkedin: { ...prev.linkedin, busy: false },
          seek: { ...prev.seek, busy: false },
        }));
        setIsStartingAll(false);
        isStartingAllRef.current = false;
        pollAll();
      }
    }
  };

  const handlePauseAll = async () => {
    if (busyRef.current.size) return;
    busyRef.current.add("linkedin"); busyRef.current.add("seek");
    setIsPausingAll(true);
    setGlobalMessage(null);

    const pauseTasks = (["linkedin", "seek"] as Platform[]).map(async (platform) => {
      const st = sources[platform].data;
      if (st && ["running", "waiting", "retrying"].includes(st.status)) {
        try {
          const updated = await sendBridgeMessage(platform, "pause");
          if (mountedRef.current) {
            setSources((prev) => ({
              ...prev,
              [platform]: { ...prev[platform], data: updated, error: null },
            }));
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : "暂停失败";
          if (mountedRef.current) {
            setSources((prev) => ({
              ...prev,
              [platform]: { ...prev[platform], error: msg },
            }));
          }
        }
      }
    });

    try {
      await Promise.allSettled(pauseTasks);
      setGlobalMessage({ type: "info", text: "已向活跃采集任务发送暂停指令。" });
    } finally {
      busyRef.current.clear();
      if (mountedRef.current) {
        setIsPausingAll(false);
        pollAll();
      }
    }
  };

  const handleSingleAction = async (platform: Platform, action: BridgeAction) => {
    if (busyRef.current.has(platform)) return;
    busyRef.current.add(platform);
    setSources((prev) => ({
      ...prev,
      [platform]: { ...prev[platform], busy: true, error: null },
    }));

    try {
      if (action === "start") {
        const res = await runStartForPlatform(platform);
        if (!res.ok) {
          setSources((prev) => ({
            ...prev,
            [platform]: { ...prev[platform], error: res.message },
          }));
        }
      } else if (action === "configure") {
        const config = await requestSetup(platform);
        try {
          const updated = await sendBridgeMessage(platform, "configure", config);
          if (mountedRef.current) {
            setSources((prev) => ({
              ...prev,
              [platform]: { connection: "connected", data: updated, error: null },
            }));
          }
        } finally {
          config.deviceToken = undefined;
        }
      } else {
        if (action === "resume" && sources[platform].data?.needsSetup) {
          const config = await requestSetup(platform);
          try { await sendBridgeMessage(platform, "configure", config); }
          finally { config.deviceToken = undefined; }
        }
        const updated = await sendBridgeMessage(platform, action);
        if (mountedRef.current) {
          setSources((prev) => ({
            ...prev,
            [platform]: { connection: "connected", data: updated, error: null },
          }));
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "操作失败";
      if (mountedRef.current) {
        setSources((prev) => ({
          ...prev,
          [platform]: { ...prev[platform], error: msg },
        }));
      }
    } finally {
      busyRef.current.delete(platform);
      if (mountedRef.current) {
        setSources((prev) => ({
          ...prev,
          [platform]: { ...prev[platform], busy: false },
        }));
      }
    }
  };

  const canPauseAny = (["linkedin", "seek"] as Platform[]).some((p) => {
    const s = sources[p].data?.status;
    return s && ["running", "waiting", "retrying"].includes(s);
  });

  const renderSourceCard = (platform: Platform, title: string, scopeDesc: string) => {
    const st = sources[platform];
    const data = st.data;
    const badge = statusBadgeInfo(st.connection, data);
    const isOffline = st.connection !== "connected" || !data;

    return (
      <div className={styles.sourceCard} data-testid={`source-card-${platform}`}>
        <div className={styles.cardHead}>
          <div className={styles.sourceIdentity}>
            <div className={styles.sourceTitleRow}>
              <h3 className={styles.sourceName}>{title}</h3>
            </div>
            <p className={styles.sourceScope}>{scopeDesc}</p>
          </div>
          <span className={`${styles.statusBadge} ${badge.className}`} data-testid={`status-${platform}`}>
            <span className={styles.statusDot} />
            {badge.text}
          </span>
        </div>

        <div className={styles.metricsGrid} aria-label={`${title} 计数统计`}>
          <div className={styles.metricItem}>
            <span className={styles.metricValue} data-testid={`metric-collected-${platform}`}>
              {isOffline ? "—" : data.collected.toLocaleString("zh-CN")}
            </span>
            <span className={styles.metricLabel}>本地已采</span>
          </div>
          <div className={styles.metricItem}>
            <span className={styles.metricValue} data-testid={`metric-pending-${platform}`}>
              {isOffline ? "—" : data.pendingSync.toLocaleString("zh-CN")}
            </span>
            <span className={styles.metricLabel}>待同步</span>
          </div>
          <div className={styles.metricItem}>
            <span className={styles.metricValue} data-testid={`metric-synced-${platform}`}>
              {isOffline ? "—" : data.synced.toLocaleString("zh-CN")}
            </span>
            <span className={styles.metricLabel}>已入库确认</span>
          </div>
        </div>

        <div className={styles.detailSection}>
          <div className={styles.timeRow} data-testid={`daily-goal-${platform}`}>
            <span>{platform === "linkedin" ? "今日有效采集" : "每日入库目标"}</span>
            <span className={styles.timeValue}>
              {platform === "linkedin"
                ? !isOffline && data.dailyTarget !== undefined && data.todayCollected !== undefined
                  ? `${data.todayCollected} / ${data.dailyTarget} 条（北京时间）`
                  : "待新版扩展确认每日目标"
                : seekDailyTarget !== undefined ? `${seekDailyTarget} 条（北京时间）` : "—"}
            </span>
          </div>
          <div className={styles.timeRow}>
            <span>下次执行</span>
            <span className={styles.timeValue} data-testid={`time-next-${platform}`}>
              {isOffline
                ? "—"
                : data.nextRunAt
                ? `${formatShanghaiTime(data.nextRunAt)} (北京时间)`
                : data.status === "waiting"
                ? "等待下一时段"
                : data.status === "running"
                ? "正在读取详情"
                : "无定时"}
            </span>
          </div>

          <div className={styles.timeRow}>
            <span>最近同步入库</span>
            <span className={styles.timeValue} data-testid={`time-sync-${platform}`}>
              {isOffline ? "—" : formatShanghaiTime(data.lastSyncAt)}
            </span>
          </div>

          {data?.requiresHuman && (
            <div className={styles.humanNotice} data-testid={`human-notice-${platform}`}>
              <span>⚠️ 需要人工处理验证码、登录或安全检查。请在浏览器中打开对应页面完成验证，然后点击“验证后继续”。</span>
            </div>
          )}

          {data?.needsSetup && !isOffline && (
            <div className={styles.messageBox} style={{ borderColor: "#fcd34d", background: "#fefce8" }}>
              <span>ℹ️ 此设备尚未配置入库凭据，点击“重新连接”或“开始采集”将自动绑定。</span>
            </div>
          )}

          {data?.rejectedSync && data.rejectedSync > 0 ? (
            <div className={styles.messageBox} style={{ color: "#b45309", borderColor: "#fde68a" }}>
              <span>未通过检查职位: {data.rejectedSync} 条（原始记录已保留）</span>
            </div>
          ) : null}

          {st.error ? (
            <div className={styles.messageBox} style={{ color: "#b91c1c", borderColor: "#fecaca", background: "#fef2f2" }} data-testid={`error-${platform}`}>
              {st.error}
            </div>
          ) : (
            <div className={styles.messageBox} data-testid={`message-${platform}`}>
              {!isOffline && Number.isInteger(data.page) && data.page > 0 ? `已保存第 ${data.page} 页进度 · ` : ""}
              {isOffline ? "未连接，请允许扩展在此本机网站运行，然后刷新本页。" : data.message || "就绪"}
            </div>
          )}
        </div>

        <div className={styles.cardActions}>
          {data?.requiresHuman || data?.canResume ? (
            <button
              type="button"
              className={`${styles.btnCardAction} ${styles.btnCardActionResume}`}
              onClick={() => handleSingleAction(platform, "resume")}
              disabled={st.busy || isOffline}
              data-testid={`btn-resume-${platform}`}
            >
              {data?.requiresHuman ? "验证后继续" : "继续采集"}
            </button>
          ) : (
            <button
              type="button"
              className={`${styles.btnCardAction} ${styles.btnCardActionPrimary}`}
              onClick={() => handleSingleAction(platform, "start")}
              disabled={st.busy || isOffline || data?.status === "running"}
              data-testid={`btn-start-${platform}`}
            >
              开始采集
            </button>
          )}

          <button
            type="button"
            className={styles.btnCardAction}
            onClick={() => handleSingleAction(platform, "pause")}
            disabled={st.busy || isOffline || !["running", "waiting", "retrying"].includes(data?.status || "")}
            data-testid={`btn-pause-${platform}`}
          >
            暂停
          </button>

          <button
            type="button"
            className={styles.btnCardAction}
            onClick={() => handleSingleAction(platform, "sync")}
            disabled={st.busy || isOffline}
            title="将已保存但未同步的数据立即提交入库"
            data-testid={`btn-sync-${platform}`}
          >
            立即同步
          </button>

          {(data?.needsSetup || isOffline) && (
            <button
              type="button"
              className={styles.btnCardAction}
              onClick={() => (isOffline ? refreshPlatform(platform) : handleSingleAction(platform, "configure"))}
              disabled={st.busy}
              data-testid={`btn-reconnect-${platform}`}
            >
              {isOffline ? "重新检测" : "重新连接"}
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <section className={styles.collectorDashboard} aria-labelledby="collector-dashboard-title" data-testid="collector-dashboard">
      <div className={styles.topBar}>
        <div className={styles.titleArea}>
          <span className={styles.eyebrow}>
            <span className={styles.pollDot} />
            自动采集调度台
          </span>
          <h2 id="collector-dashboard-title" className={styles.mainTitle}>
            采集控制台
          </h2>
          <p className={styles.subTitle}>
            一键启动 LinkedIn 与 SEEK，自动保存进度与同步职位。
          </p>
        </div>

        <div className={styles.topActions}>
          <button
            type="button"
            className={styles.btnStartAll}
            onClick={handleStartAll}
            disabled={isStartingAll || isPausingAll || sources.linkedin.busy || sources.seek.busy}
            data-testid="btn-start-all"
          >
            {isStartingAll ? "正在启动采集…" : "一键开始采集"}
          </button>

          <button
            type="button"
            className={styles.btnPauseAll}
            onClick={handlePauseAll}
            disabled={isPausingAll || !canPauseAny}
            data-testid="btn-pause-all"
          >
            {isPausingAll ? "正在暂停…" : "全部暂停"}
          </button>

          <button
            type="button"
            className={styles.btnRefresh}
            onClick={pollAll}
            disabled={isStartingAll || isPausingAll}
            data-testid="btn-refresh"
          >
            刷新状态
          </button>

          <span className={styles.pollIndicator} title={`每 8 秒自动轮询一次 (已更新 ${pollCount} 次)`}>
            <span className={`${styles.pollDot} ${typeof document !== "undefined" && document.visibilityState === "hidden" ? styles.pollDotPaused : ""}`} />
            8s 自动轮询
          </span>
        </div>
      </div>

      {globalMessage && (
        <div
          className={`${styles.globalAlert} ${
            globalMessage.type === "error"
              ? styles.alertError
              : globalMessage.type === "warning"
              ? styles.alertWarning
              : styles.alertInfo
          }`}
          role="alert"
          data-testid="global-alert"
        >
          {globalMessage.text}
        </div>
      )}

      <div className={styles.sourceGrid}>
        {renderSourceCard("linkedin", "LinkedIn 领英", "美国全职业 + 澳洲 Registered Nurse")}
        {renderSourceCard("seek", "SEEK 澳洲", "澳洲 Registered Nurse 定向采集")}
      </div>

      <details className={styles.helpDetails} data-testid="help-details">
        <summary className={styles.helpSummary}>首次使用与故障排查说明</summary>
        <div className={styles.helpContent}>
          <p>
            <strong>首次使用或升级扩展后连接步骤：</strong>
          </p>
          <ol className={styles.helpList}>
            <li>
              打开 Edge 浏览器扩展管理页（地址栏输入 <code>edge://extensions</code>），开启“开发人员模式”。
            </li>
            <li>
              对 <code>clients/linkedin_edge_extension</code> 与 <code>clients/seek_edge_extension</code> 分别点击“重新加载”。
            </li>
            <li>
              如果扩展提示访问权限请求（访问 <code>http://localhost:3000</code>），请点击“允许”。
            </li>
            <li>
              刷新当前页面，控制台即可通过本地消息桥自动检测到两个扩展并显示真实状态。
            </li>
            <li>
              点击“一键开始采集”，系统将自动为扩展建立设备凭据并触发日常采集，无需人工输入令牌。
            </li>
          </ol>
          <p style={{ marginTop: 10 }}>
            <strong>注意事项：</strong>
            后台服务需保持在 <code>8010</code> 端口运行；如遇安全验证或人机验证码，任务将自动暂停，请在浏览器对应标签页完成验证后点击卡片中的“验证后继续”。
          </p>
        </div>
      </details>
    </section>
  );
}
