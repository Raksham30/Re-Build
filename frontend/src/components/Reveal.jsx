import { useEffect, useRef } from "react";
export default function Reveal({ as: Tag = "div", className = "", delay = 0, children, ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || !("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    node.dataset.revealReady = "true";
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { node.dataset.revealed = "true"; observer.unobserve(node); }
    }, { threshold: 0.14, rootMargin: "0px 0px -6% 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return <Tag ref={ref} className={("reveal " + className).trim()} style={{ "--reveal-delay": delay + "ms" }} {...props}>{children}</Tag>;
}
