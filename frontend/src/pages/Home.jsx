import { Link } from "react-router-dom";
import Reveal from "../components/Reveal";
import ResearchArt from "../components/ResearchArt";
const steps=[
 {n:"01",title:"Gather your papers",text:"Create a workspace for a question or project. Upload the papers you want to think with."},
 {n:"02",title:"Ask across the library",text:"Select the studies that matter and ask about their methods, evidence, or results."},
 {n:"03",title:"Follow the connections",text:"Compare claims, notice possible conflicts, and see where the literature leaves room."},
 {n:"04",title:"Write with sources in view",text:"Shape a review from your ideas and the papers in your workspace, with references attached."}
];
const Arrow=()=> <span className="arrow-mark" aria-hidden="true">↗</span>;
export default function Home(){return <main className="public-site home-page">
 <section className="hero-field"><div className="hero-grain" aria-hidden="true"/>
  <div className="hero-copy"><p className="eyebrow eyebrow--light"><span className="eyebrow-dot"/> A workspace for connected research</p>
   <h1 className="hero-title"><span className="hero-line">Read closely.</span><span className="hero-line hero-line--indent">Think across.</span><span className="hero-line hero-line--soft">Find what connects.</span></h1>
   <p className="hero-description">Bring your papers together. Ask better questions, trace every answer to its source, and see the research landscape take shape.</p>
   <div className="hero-actions"><Link className="button button--ivory" to="/login">Start researching <Arrow/></Link><a className="text-link text-link--light" href="#the-work">Explore the approach <span aria-hidden="true">↓</span></a></div>
  </div><ResearchArt/>
  <div className="hero-footnote"><span>FIELD GUIDE / 01</span><span>Evidence, in context</span><a href="#the-work" aria-label="Scroll to the research workflow">Scroll to explore ↓</a></div>
 </section>
 <section className="index-strip" id="the-work" aria-label="Research workflow">
  {[["01","Library","A place for each question","#library"],["02","Connections","Compare what papers say","#connections"],["03","Open questions","Look for what is missing","#gaps"],["04","Writing","Build a cited review","#writing"]].map(([n,t,d,h])=><a className="index-entry" href={h} key={n}><span className="index-number">{n}</span><span className="index-title">{t}</span><span className="index-caption">{d}</span><span className="index-arrow">↗</span></a>)}
 </section>
 <section className="story-section story-section--intro" id="library">
  <Reveal className="story-kicker"><span className="section-index">A quieter kind of research tool</span></Reveal>
  <div className="story-grid"><Reveal className="story-heading-wrap"><h2 className="story-heading">A paper is a beginning.<br/><em>The conversation is larger.</em></h2></Reveal>
   <Reveal className="story-copy" delay={100}><p>Research lives between pages: a method repeated, a result in tension, a question no single study can answer.</p><p>This workspace helps you hold those papers together, ask across them, and keep the evidence close as your thinking develops.</p><Link to="/about" className="underlined-link">Why this approach <Arrow/></Link></Reveal>
  </div>
 </section>
 <section className="story-section story-section--library">
  <Reveal className="library-illustration" aria-hidden="true"><div className="paper-stack paper-stack--back"><span>METHODS</span><i/><i/><i/></div><div className="paper-stack paper-stack--front"><span>YOUR RESEARCH LIBRARY</span><strong>One question,<br/>many perspectives.</strong><i/><i/></div><span className="pencil-mark">NOTES / SOURCES / IDEAS</span></Reveal>
  <Reveal className="story-copy story-copy--narrow"><span className="section-index">01 — Build a working library</span><h2 className="story-heading story-heading--medium">Keep the source<br/>within reach.</h2><p>Bring PDFs into a workspace shaped around your project. Rename and organize your papers, then choose which studies should inform a question or draft.</p><Link to="/login" className="underlined-link">Create a workspace <Arrow/></Link></Reveal>
 </section>
 <section className="story-section story-section--contrast" id="connections">
  <Reveal className="contrast-copy"><span className="section-index section-index--light">02 — Read across studies</span><h2 className="story-heading story-heading--light">The useful answer<br/>often lives <em>between</em><br/>the papers.</h2><p>Ask about methods, datasets, results, and limitations. Answers arrive with paper, section, and page references so you can return to the evidence.</p><Link to="/login" className="button button--outline-light">Explore the workspace <Arrow/></Link></Reveal>
  <Reveal className="evidence-spread" delay={140}><div className="evidence-label">A QUESTION, HELD AGAINST THE RECORD</div><div className="question-slip">How do the reported evaluations differ?</div><div className="evidence-row"><span className="evidence-marker">A</span><div><strong>Paper A · Evaluation</strong><p>Reports results on a curated benchmark.</p><small>SECTION 04 · PAGE 7</small></div></div><div className="evidence-row"><span className="evidence-marker evidence-marker--sage">B</span><div><strong>Paper B · Limitations</strong><p>Notes that the benchmark omits longer contexts.</p><small>SECTION 06 · PAGE 12</small></div></div><div className="evidence-foot">Illustrative layout · Answers cite uploaded sources</div></Reveal>
 </section>
 <section className="story-section story-section--compare">
  <Reveal className="story-copy story-copy--narrow"><span className="section-index">03 — Notice where accounts diverge</span><h2 className="story-heading story-heading--medium">Agreement is useful.<br/><em>Disagreement is a clue.</em></h2><p>Possible contradictions are surfaced as findings after an upload, and you can compare selected papers when a question calls for a closer look.</p><Link to="/login" className="underlined-link">See how findings work <Arrow/></Link></Reveal>
  <Reveal className="comparison-art" aria-label="Two paper claims compared side by side"><div className="comparison-thread"><span>CLAIM A</span><i/><b>↔</b><i/><span>CLAIM B</span></div><div className="comparison-columns"><div><small>STUDY 01</small><strong>Improvement observed</strong><span>p. 08 · Results</span></div><div><small>STUDY 02</small><strong>Effect not reproduced</strong><span>p. 11 · Discussion</span></div></div><p>Compare claims with their source context.</p></Reveal>
 </section>
 <section className="gap-interlude" id="gaps"><Reveal className="gap-stamp"><span>LOOK AGAIN</span><b>?</b></Reveal><Reveal className="gap-copy" delay={100}><span className="section-index section-index--light">04 — Make room for the next question</span><h2 className="story-heading story-heading--light">What has not<br/>been asked yet?</h2><p>Gap analysis looks across your workspace and offers a grounded view of underexplored questions, with citations to the papers behind it.</p><Link to="/login" className="text-link text-link--light">Find a new direction <Arrow/></Link></Reveal><span className="gap-orbit gap-orbit--one" aria-hidden="true"/><span className="gap-orbit gap-orbit--two" aria-hidden="true"/></section>
 <section className="story-section story-section--writing"><Reveal className="writing-sheet"><div className="sheet-topline"><span>WORKING DRAFT</span><span>WITH SOURCES IN VIEW</span></div><h3>From question<br/>to literature review.</h3><p>01 &nbsp; Introduction <i>Ground the question in the field. [1, 2]</i></p><p>02 &nbsp; Approaches <i>Compare methods and their limits. [2, 4]</i></p><p>03 &nbsp; Open questions <i>Identify where evidence thins. [1, 3]</i></p><div className="sheet-rule"/><small>References are verified against your uploaded papers.</small></Reveal><Reveal className="story-copy story-copy--narrow" delay={110}><span className="section-index">05 — Let your ideas lead</span><h2 className="story-heading story-heading--medium">A draft with its<br/>evidence attached.</h2><p>Plan a review, shape the outline, and draft sections using your own research ideas alongside selected literature. Revise a section and export the finished markdown.</p><Link to="/about#method" className="underlined-link">Read our working principles <Arrow/></Link></Reveal></section>
 <section className="closing-field"><Reveal><span className="eyebrow eyebrow--light">Your next question is waiting</span><h2>Bring the papers.<br/><em>Follow what they reveal.</em></h2><Link to="/login" className="button button--ivory">Start a research workspace <Arrow/></Link></Reveal><span className="closing-flower" aria-hidden="true">✳</span></section>
 <footer className="site-footer"><span>Research Paper Assistant</span><span>Read closely. Think across.</span><Link to="/about">About the project ↗</Link></footer>
</main>}
