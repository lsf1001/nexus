"""生成 Nexus N monogram 图标。
设计:深炭灰圆角矩形底 + 几何白色 N 字 + 极简底部刻度线。
"""
from PIL import Image, ImageDraw

SIZE = 1024
BG = (28, 28, 30, 255)         # 深炭灰 #1c1c1e
FG = (250, 250, 250, 255)      # 近白 #fafafa
ACCENT = (180, 132, 255, 255)  # 紫蓝 accent #b484ff — N 字右上角小星点

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 1) 圆角矩形底(macOS 标准圆角 ~22.37% → 229px @1024)
RADIUS = 229
draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=RADIUS, fill=BG)

# 2) 几何 N 字(粗体、几何化)
#    左竖、右竖、斜笔(梯形)
STROKE = 96  # 主笔粗
# 左竖
draw.rectangle((270, 240, 270 + STROKE, 240 + 544), fill=FG)
# 右竖
draw.rectangle((SIZE - 270 - STROKE, 240, SIZE - 270, 240 + 544), fill=FG)
# 斜笔(梯形连接左竖顶 ↔ 右竖底)
# 左竖顶中央: (270 + STROKE/2, 240) = (318, 240)
# 右竖底中央: (SIZE - 270 - STROKE/2, 240 + 544) = (658, 784)
# 沿斜笔方向偏移 STROKE/2 形成梯形
import math
p1 = (318, 240)
p2 = (658, 784)
dx, dy = p2[0] - p1[0], p2[1] - p1[1]
length = math.hypot(dx, dy)
ux, uy = dx / length, dy / length  # 单位向量
# 垂直方向(-uy, ux) 偏移 STROKE/2
nx, ny = -uy, ux
h = STROKE / 2
poly = [
    (p1[0] + nx * h, p1[1] + ny * h),
    (p1[0] - nx * h, p1[1] - ny * h),
    (p2[0] - nx * h, p2[1] - ny * h),
    (p2[0] + nx * h, p2[1] + ny * h),
]
draw.polygon(poly, fill=FG)

# 3) 极简底部刻度线(品牌识别):3 道短横线暗示「会话/记忆/工具」
BAR_Y = 880
BAR_H = 6
BAR_GAP = 16
bar_total_w = 96 + 8 + 96 + 8 + 96  # 三段 + 两间隔 = 304
start_x = (SIZE - bar_total_w) // 2
for i in range(3):
    x0 = start_x + i * (96 + 8)
    # 透明度 30% 渐变:左最弱,右最强
    alpha = 90 + i * 80  # 90, 170, 250
    draw.rectangle(
        (x0, BAR_Y, x0 + 96, BAR_Y + BAR_H),
        fill=(FG[0], FG[1], FG[2], alpha),
    )

# 4) 右上方小星点(夜小白品牌呼应)
star_x, star_y = SIZE - 270, 270
draw.ellipse((star_x - 28, star_y - 28, star_x + 28, star_y + 28), fill=ACCENT)
# 十字光芒
draw.rectangle((star_x - 6, star_y - 56, star_x + 6, star_y - 32), fill=ACCENT)
draw.rectangle((star_x - 6, star_y + 32, star_x + 6, star_y + 56), fill=ACCENT)
draw.rectangle((star_x - 56, star_y - 6, star_x - 32, star_y + 6), fill=ACCENT)
draw.rectangle((star_x + 32, star_y - 6, star_x + 56, star_y + 6), fill=ACCENT)

img.save("/Users/yxb/projects/nexus/desktop/build/icon-design/icon-1024.png")
print(f"Saved icon-1024.png ({SIZE}x{SIZE})")