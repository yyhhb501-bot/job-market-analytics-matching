import { BoardAdmin } from "@/components/BoardAdmin";
import { getBoards, type Board } from "@/lib/api";
import { labelSource } from "@/lib/format";

export const dynamic = "force-dynamic";

function groupByProvider(boards: Board[]): Map<string, Board[]> {
  const grouped = new Map<string, Board[]>();
  for (const board of boards) {
    const list = grouped.get(board.provider) ?? [];
    list.push(board);
    grouped.set(board.provider, list);
  }
  return grouped;
}

export default async function BoardsPage() {
  let boards: Board[] = [];
  let error: string | null = null;
  try {
    boards = await getBoards();
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  const grouped = groupByProvider(boards);
  const enabled = boards.filter((board) => board.enabled).length;

  return (
    <>
      <section className="hero">
        <h1>公司看板（ATS）</h1>
        <p>
          共 {boards.length} 个看板，其中启用 {enabled} 个。可自动发现公司使用的 ATS 并校验后加入。
        </p>
      </section>

      {error ? <div className="notice">无法连接 API（{error}）。</div> : null}

      <BoardAdmin />

      {boards.length === 0 && !error ? (
        <p className="empty">还没有公司看板。运行 `python -m apps.worker.main boards-import` 导入，或在上方添加。</p>
      ) : (
        Array.from(grouped.entries())
          .sort((a, b) => b[1].length - a[1].length)
          .map(([provider, items]) => (
            <section key={provider} className="alert-block">
              <div className="alert-head">
                <h2>
                  {labelSource(provider)} <span className="engine">（{provider}）</span>
                </h2>
                <div className="alert-stats">
                  <span>{items.length} 个看板</span>
                  <span>{items.filter((board) => board.enabled).length} 个启用</span>
                </div>
              </div>
              <div className="table-wrap">
                <table className="runs-table">
                  <thead>
                    <tr>
                      <th>公司</th>
                      <th>标识</th>
                      <th>状态</th>
                      <th>岗位数</th>
                      <th>连续失败</th>
                      <th>上次校验</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((board) => (
                      <tr key={board.id}>
                        <td>{board.company_name ?? board.board_token}</td>
                        <td>{board.board_token}</td>
                        <td>{board.enabled ? "启用" : "停用"}</td>
                        <td>{board.last_job_count}</td>
                        <td>{board.consecutive_failures}</td>
                        <td>{board.last_checked_at?.slice(0, 10) ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))
      )}
    </>
  );
}
