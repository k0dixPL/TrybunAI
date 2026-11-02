from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


SIZE = 4096
SCALE = 4
ICON_SIZE = 1024


def p(value):
    """Convert design coordinates at 1024px to supersampled coordinates."""
    return int(round(value * SCALE))


def gradient(size, stops):
    """Build a vertical RGB gradient from (position, hex_color) stops."""
    width, height = size
    colors = []

    for y in range(height):
        position = y / max(1, height - 1)
        for index in range(len(stops) - 1):
            start, start_color = stops[index]
            end, end_color = stops[index + 1]
            if start <= position <= end:
                amount = (position - start) / max(1e-9, end - start)
                start_rgb = tuple(int(start_color[i:i + 2], 16) for i in (1, 3, 5))
                end_rgb = tuple(int(end_color[i:i + 2], 16) for i in (1, 3, 5))
                colors.append(
                    tuple(
                        round(start_rgb[channel] * (1 - amount) + end_rgb[channel] * amount)
                        for channel in range(3)
                    )
                )
                break
        else:
            color = stops[-1][1]
            colors.append(tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)))

    image = Image.new("RGB", (1, height))
    image.putdata(colors)
    return image.resize((width, height), Image.Resampling.BILINEAR)


def gradient_layer(size, stops, mask):
    layer = gradient(size, stops).convert("RGBA")
    layer.putalpha(mask)
    return layer


def draw_bubble_mask(bounds, radius, tail_points):
    mask = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        tuple(p(value) for value in bounds),
        radius=p(radius),
        fill=255,
    )
    draw.polygon([(p(x), p(y)) for x, y in tail_points], fill=255)
    return mask


def circle_mask(center_x, center_y, radius):
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse(
        (
            p(center_x - radius),
            p(center_y - radius),
            p(center_x + radius),
            p(center_y + radius),
        ),
        fill=255,
    )
    return mask


def main():
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    outer_mask = draw_bubble_mask(
        (38, 55, 986, 825),
        150,
        ((250, 800), (185, 970), (430, 800)),
    )
    inner_mask = draw_bubble_mask(
        (62, 79, 962, 801),
        126,
        ((276, 790), (226, 920), (396, 790)),
    )

    shadow_mask = ImageChops.offset(outer_mask, 0, p(20)).filter(
        ImageFilter.GaussianBlur(p(18))
    )
    shadow_mask = shadow_mask.point(lambda value: round(value * 0.55))
    shadow = Image.new("RGBA", (SIZE, SIZE), (8, 10, 14, 0))
    shadow.putalpha(shadow_mask)
    canvas = Image.alpha_composite(canvas, shadow)

    rim = gradient_layer(
        (SIZE, SIZE),
        [
            (0.00, "#F7D58B"),
            (0.18, "#B87834"),
            (0.42, "#E5B85F"),
            (0.68, "#87502A"),
            (0.86, "#D69B49"),
            (1.00, "#69402A"),
        ],
        outer_mask,
    )
    canvas = Image.alpha_composite(canvas, rim)

    highlight_mask = Image.new("L", (SIZE, SIZE), 0)
    highlight_draw = ImageDraw.Draw(highlight_mask)
    highlight_draw.line(
        [(p(166), p(83)), (p(838), p(83))],
        fill=170,
        width=p(9),
    )
    highlight_draw.line(
        [(p(84), p(190)), (p(84), p(510))],
        fill=105,
        width=p(7),
    )
    highlight_mask = highlight_mask.filter(ImageFilter.GaussianBlur(p(11)))
    highlight_mask = ImageChops.multiply(highlight_mask, outer_mask)
    highlight = Image.new("RGBA", (SIZE, SIZE), (255, 235, 184, 0))
    highlight.putalpha(highlight_mask)
    canvas = Image.alpha_composite(canvas, highlight)

    interior = gradient_layer(
        (SIZE, SIZE),
        [
            (0.00, "#30343B"),
            (0.42, "#20242B"),
            (1.00, "#15191F"),
        ],
        inner_mask,
    )
    canvas = Image.alpha_composite(canvas, interior)

    # A broad, muted gold line links the four model nodes.
    connector = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    connector_draw = ImageDraw.Draw(connector)
    node_centers = (224, 416, 608, 800)
    node_y = 443
    connector_draw.line(
        [(p(node_centers[0]), p(node_y))]
        + [(p(x), p(node_y)) for x in node_centers[1:]],
        fill=(194, 145, 76, 210),
        width=p(22),
    )
    canvas = Image.alpha_composite(canvas, connector)

    nodes = [
        {
            "x": node_centers[0],
            "stops": [(0.0, "#F09A76"), (1.0, "#B84F37")],
        },
        {
            "x": node_centers[1],
            "stops": [(0.0, "#48515B"), (1.0, "#20262D")],
        },
        {
            "x": node_centers[2],
            "stops": [(0.0, "#4285F4"), (1.0, "#9B72CB")],
        },
        {
            "x": node_centers[3],
            "stops": [(0.0, "#B8D6A7"), (1.0, "#658C70")],
        },
    ]

    for index, node in enumerate(nodes):
        x = node["x"]

        # A light outer ring keeps each node distinct at small icon sizes.
        ring = circle_mask(x, node_y, 77)
        ring_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ring_layer.paste((244, 218, 169, 255), (0, 0, SIZE, SIZE), ring)
        canvas = Image.alpha_composite(canvas, ring_layer)

        face_mask = circle_mask(x, node_y, 64)
        face = gradient_layer((SIZE, SIZE), node["stops"], face_mask)
        canvas = Image.alpha_composite(canvas, face)

        if index == 1:
            # Codex: graphite center with a bright diamond accent.
            diamond = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            diamond_draw = ImageDraw.Draw(diamond)
            diamond_draw.polygon(
                [
                    (p(x), p(node_y - 29)),
                    (p(x + 27), p(node_y)),
                    (p(x), p(node_y + 29)),
                    (p(x - 27), p(node_y)),
                ],
                fill=(238, 237, 226, 255),
            )
            canvas = Image.alpha_composite(canvas, diamond)

        # A small soft glint adds a restrained polished finish.
        glint = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        glint_draw = ImageDraw.Draw(glint)
        glint_draw.ellipse(
            (p(x - 36), p(node_y - 43), p(x - 8), p(node_y - 15)),
            fill=(255, 255, 255, 65),
        )
        canvas = Image.alpha_composite(canvas, glint)

    result = canvas.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    output_path = Path(__file__).parent / "assets" / "icon-source.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, format="PNG")


if __name__ == "__main__":
    main()
