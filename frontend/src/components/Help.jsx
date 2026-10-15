import { useRef, useState } from "react";

const WIDTH = 240;

// A "?" badge that explains a term. Opens on hover, keyboard focus, or tap. The bubble is
// positioned against the window so tables and cards can't clip it.
export default function Help({ text }) {
  const [pos, setPos] = useState(null);
  const ref = useRef(null);

  const show = () => {
    const r = ref.current.getBoundingClientRect();
    const left = Math.min(Math.max(r.left + r.width / 2 - WIDTH / 2, 8), window.innerWidth - WIDTH - 8);
    const above = r.top > 140;
    setPos({ left, top: above ? r.top - 8 : r.bottom + 8, above });
  };
  const hide = () => setPos(null);

  return (
    <span
      ref={ref}
      className="help"
      tabIndex={0}
      role="button"
      aria-label={text}
      aria-expanded={!!pos}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onClick={(e) => {
        e.stopPropagation();
        pos ? hide() : show();
      }}
    >
      ?
      {pos && (
        <span
          className="help-pop"
          role="tooltip"
          style={{ left: pos.left, top: pos.top, width: WIDTH, transform: pos.above ? "translateY(-100%)" : "none" }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
