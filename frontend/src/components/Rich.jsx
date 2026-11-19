// Lightweight markdown renderer -- not a full parser, just the subset
// Gemini's responses actually use: ### / ## headers, **bold**, and
// paragraph breaks. Enough to stop raw "### **Title**" showing as
// literal characters, without pulling in a full markdown dependency.
function renderInlineBold(text, keyPrefix) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
      : part
  );
}

export function renderRich(text) {
  // Split into blocks line-by-line (not just on blank lines) so a heading
  // immediately followed by content on the next line -- with no blank
  // line between them, which is exactly what real Gemini output looks
  // like -- still gets detected as its own heading block.
  const lines = text.split("\n");
  const blocks = [];
  let paragraphLines = [];

  const flush = () => {
    if (paragraphLines.length) {
      blocks.push({ type: "p", text: paragraphLines.join("\n").trim() });
      paragraphLines = [];
    }
  };

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      flush();
      blocks.push({ type: "h", level: headingMatch[1].length, text: headingMatch[2] });
    } else if (line.trim() === "") {
      flush();
    } else {
      paragraphLines.push(line);
    }
  }
  flush();

  return blocks.map((b, i) => {
    if (b.type === "h") {
      const content = renderInlineBold(b.text, `h${i}`);
      const Tag = b.level === 1 ? "h3" : b.level === 2 ? "h4" : "h5";
      return <Tag key={i} className="answer-heading">{content}</Tag>;
    }
    return <p key={i} className="answer-paragraph">{renderInlineBold(b.text, `p${i}`)}</p>;
  });
}

export default function Rich({ text }) {
  return <div className="answer-text">{renderRich(text || "")}</div>;
}
