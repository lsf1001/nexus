interface SketchLineProps {
  position: 'top-right' | 'bottom-left';
}

/**
 * 原型里的两条手绘弧线。
 * - top-right：森林绿弧（呼应侧边栏主色）
 * - bottom-left：茶叶色弧（呼应茶色 token）
 *
 * 用 inline SVG 避免外部资源依赖，颜色和透明度走 CSS 变量。
 */
export function SketchLine({ position }: SketchLineProps) {
  if (position === 'top-right') {
    return (
      <svg
        className="sketch-line sketch-line--top-right"
        viewBox="0 0 120 40"
        width="120"
        height="40"
        aria-hidden="true"
      >
        <ellipse
          cx="60"
          cy="20"
          rx="56"
          ry="14"
          fill="none"
          stroke="var(--sage)"
          strokeWidth="1.5"
          strokeOpacity="0.42"
          transform="rotate(-17 60 20)"
        />
        <ellipse
          cx="60"
          cy="20"
          rx="40"
          ry="9"
          fill="var(--sage)"
          fillOpacity="0.14"
          transform="rotate(-17 60 20)"
        />
      </svg>
    );
  }

  return (
    <svg
      className="sketch-line sketch-line--bottom-left"
      viewBox="0 0 80 30"
      width="80"
      height="30"
      aria-hidden="true"
    >
      <ellipse
        cx="40"
        cy="15"
        rx="36"
        ry="9"
        fill="none"
        stroke="var(--tea)"
        strokeWidth="1.5"
        strokeOpacity="0.42"
        transform="rotate(22 40 15)"
      />
      <ellipse
        cx="40"
        cy="15"
        rx="22"
        ry="5"
        fill="var(--tea)"
        fillOpacity="0.16"
        transform="rotate(22 40 15)"
      />
    </svg>
  );
}
