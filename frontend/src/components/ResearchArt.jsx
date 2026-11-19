import { useEffect, useRef } from "react";
export default function ResearchArt() {
  const art = useRef(null);
  useEffect(() => {
    const node = art.current;
    if (!node || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = node.getBoundingClientRect();
        const progress = (window.innerHeight * 0.48 - rect.top) * 0.035;
        node.style.setProperty("--drift", Math.max(-22, Math.min(22, progress)) + "px");
      });
    };
    update(); window.addEventListener("scroll", update, { passive: true }); window.addEventListener("resize", update);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", update); window.removeEventListener("resize", update); };
  }, []);
  return <div className="research-art" ref={art} aria-label="Illustration of an open research notebook connecting ideas" role="img">
    <div className="art-orbit art-orbit--one" /><div className="art-orbit art-orbit--two" />
    <span className="art-note art-note--top">field notes · 01</span><span className="art-note art-note--side">follow the evidence</span>
    <svg viewBox="0 0 620 540" className="notebook-art" aria-hidden="true">
      <path className="art-sun" d="M444 92c0-34 27-61 61-61s61 27 61 61-27 61-61 61-61-27-61-61Z"/>
      <path className="sun-ray" d="M505 8v-22m0 221v-22m83-83h22M400 92h22m142-59 16-16m-150 150 16-16m118 0 16 16M423 17l16 16"/>
      <path className="sprig" d="M491 329c23-50 47-94 88-131m-57 80c-2-25 8-39 27-47 1 21-7 37-27 47Zm20-38c-1-23 7-37 24-43 2 19-5 34-24 43Zm-39 68c-18-20-35-25-52-15 11 18 29 23 52 15Z"/>
      <path className="book-shadow" d="M79 434c95-32 183-27 239 1 70-35 148-40 220-12l-15 51c-80-18-147-10-205 24-65-34-146-43-226-11Z"/>
      <path className="book-left" d="M92 182c77-20 151-8 226 31v239c-77-36-151-43-226-19V182Z"/><path className="book-right" d="M318 213c70-37 145-49 226-31v251c-77-23-152-17-226 19V213Z"/>
      <path className="book-edge" d="M318 213v239M92 182c75-18 151-7 226 31 75-38 151-49 226-31"/>
      <path className="page-line" d="M122 224c50-11 101-2 151 20m-149 17c48-9 97-1 145 18m-145 18c46-8 91 0 137 17m-137 18c40-6 77 0 115 13m-116 22c35-5 67 0 99 10"/>
      <path className="page-line page-line--right" d="M361 243c47-19 96-27 149-20m-146 39c45-17 92-25 139-20m-136 40c41-14 83-21 125-18m-122 39c36-11 71-17 107-16m-104 37c28-8 56-12 84-12"/>
      <path className="margin-mark" d="m139 302 8 8 15-20m226 47 8 8 15-20"/><path className="thread" d="M308 213c6 65 7 148 10 239"/>
      <circle className="node node--one" cx="178" cy="133" r="18"/><circle className="node node--two" cx="295" cy="98" r="12"/><circle className="node node--three" cx="390" cy="149" r="15"/>
      <path className="connection" d="m195 127 88-25m23 2 71 39m-177 8 104 55m104-44-75 51"/><path className="tiny-star" d="m113 99 5 13 13 5-13 5-5 13-5-13-13-5 13-5Zm352 173 4 10 10 4-10 4-4 10-4-10-10-4 10-4Z"/>
    </svg>
  </div>;
}
