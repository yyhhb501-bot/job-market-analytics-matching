import Link from "next/link";
import {getMethodology,type Methodology} from "@/lib/api";

export const dynamic="force-dynamic";
const labels:Record<string,string>={keyword_baseline:"关键词规则",pure_svm:"TF-IDF + Linear SVM",online_hybrid:"线上规则优先与模型回退"};
export default async function MethodologyPage(){
  let data:Methodology={available:false};
  try {data=await getMethodology();} catch {data={available:false,message:"实验服务暂不可用，请稍后刷新。"};}
  return <>
    <section className="hero"><h1>方法与可复现实验</h1><p>查看项目如何采集、去重和排序，以及目前能被证据支持的实验结论。</p></section>
    <h2 className="section-title">数据与匹配流程</h2>
    <p>多源采集 → 字段标准化 → 来源 ID、规范链接与内容去重 → 职业/资历分类 → 可展示范围校验 → 搜索与简历匹配。</p>
    <p>匹配使用词元特征哈希、L2 归一化与余弦相似度，再结合关键词覆盖、标题权重和时效；这是词法相关性方法，对同义表达和上下文理解有局限。没有兼容向量时明确降级为关键词排序。</p>
    <p><Link href="/collection">真实采集统计</Link>{" · "}<Link href="/demo/match">免注册匹配演示</Link></p>
    <h2 className="section-title">数据范围与结果边界</h2>
    <div className="notice">采集统计来自真实数据库；演示页的虚构示例职位只用于体验算法，不是采集成果。默认分类实验使用合成模板，尚无人工标注的真实职位留出集，不能据此声称真实准确率提升或复现简历中的 0.68→0.84。</div>
    {data.available?<>
      <p>本次产物：{data.corpus_scope==="synthetic_only"?"仅合成模板样本":data.corpus_scope}；训练 {data.train_count} 条，测试 {data.test_count} 条，随机种子 {data.seed}。</p>
      <p>同模板及重复组整体切分，TF-IDF 只在训练集拟合。三个策略使用同一留出集；overall 为职业与资历两个 Macro-F1 的等权均值。</p>
      <div className="table-wrap"><table className="runs-table"><thead><tr><th>策略</th><th>职业 Macro-F1</th><th>资历 Macro-F1</th><th>两任务均值</th></tr></thead><tbody>{data.strategies?.map(row=><tr key={row.name}><td>{labels[row.name]||row.name}</td><td>{row.occupation_macro_f1.toFixed(4)}</td><td>{row.seniority_macro_f1.toFixed(4)}</td><td>{row.overall_macro_f1.toFixed(4)}</td></tr>)}</tbody></table></div>
      <p className="small">数据 SHA-256：<code style={{overflowWrap:"anywhere"}}>{data.dataset_sha256}</code></p>
      <p>{data.generalisation_status}</p>
    </>:<p className="empty">{data.message||"暂无已验证的实验产物。"}</p>}
    <h2 className="section-title">本地复现</h2><pre><code>uv sync --frozen --extra dev{"\n"}uv run python -m scripts.train_and_eval_classifier</code></pre>
    <p>产物包含 metrics JSON、逐条预测、混淆矩阵和错误案例，报告由指标生成。默认不会读取私人数据库；精确复现还需相同数据哈希和依赖版本。</p>
  </>;
}
