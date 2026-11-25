"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    """Kiểm tra định dạng và hình học của từng dòng nhãn trong toàn bộ dataset."""
    label_cfg = cfg["label_format"]
    overflow_tol = label_cfg["overflow_tol"]
    min_box_px = label_cfg["min_box_px"]
    max_box_frac = label_cfg["max_box_frac"]
    dup_box_iou = label_cfg["dup_box_iou"]
    num_classes = len(ds.classes)

    issues = []

    for label_file in ds.label_files():
        image_stem = label_file.stem
        lines = ds.read_label_lines(image_stem)
        if not lines:
            continue

        image_size = ds.image_size(image_stem)
        seen_boxes = []

        for line_number, line_text in lines:
            # 1. Kiểm tra định dạng 5 cột số hợp lệ
            try:
                class_id, center_x, center_y, width, height = parse_yolo_line(line_text)
            except ValueError as error:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BAD_FORMAT",
                        image=image_stem,
                        message=f"dòng nhãn sai định dạng: {error}",
                        line=line_number,
                    )
                )
                continue

            # 2. Kiểm tra ID lớp có nằm trong khoảng 0..num_classes-1 hay không
            if class_id < 0 or class_id >= num_classes:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BAD_CLASS_ID",
                        image=image_stem,
                        message=f"ID lớp không hợp lệ: {class_id} (hợp lệ: 0..{num_classes - 1})",
                        line=line_number,
                        extra={"class_id": class_id},
                    )
                )
                continue

            # 3. Kiểm tra kích thước box bằng 0 hoặc âm
            if width <= 0 or height <= 0:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BOX_ZERO",
                        image=image_stem,
                        message=f"box có chiều rộng hoặc chiều cao <= 0 (w={width}, h={height})",
                        line=line_number,
                    )
                )
                continue

            # 4. Kiểm tra box tràn ra ngoài khung ảnh [0, 1] vượt quá overflow_tol
            left = center_x - width / 2.0
            right = center_x + width / 2.0
            top = center_y - height / 2.0
            bottom = center_y + height / 2.0

            overflow = max(0.0, -left, right - 1.0, -top, bottom - 1.0)
            if overflow > overflow_tol:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BOX_OUT_OF_IMAGE",
                        image=image_stem,
                        message=f"box tràn khỏi ảnh {overflow:.4f} (> {overflow_tol})",
                        line=line_number,
                        extra={"overflow": round(overflow, 6)},
                    )
                )

            # 5. Kiểm tra box trùng lặp với một dòng trước đó trong cùng ảnh và cùng lớp
            current_box = (center_x, center_y, width, height)
            for prev_class_id, prev_box in seen_boxes:
                if prev_class_id == class_id:
                    overlap_iou = iou_xywh(prev_box, current_box)
                    if overlap_iou > dup_box_iou:
                        issues.append(
                            Issue(
                                check="label_format",
                                severity=ERROR,
                                code="DUP_BOX",
                                image=image_stem,
                                message=f"box trùng với dòng trước cùng lớp (IoU={overlap_iou:.3f})",
                                line=line_number,
                                extra={"iou": round(overlap_iou, 4)},
                            )
                        )
                        break

            seen_boxes.append((class_id, current_box))

            # 6. Cảnh báo box quá nhỏ (cạnh ngắn theo pixel < min_box_px)
            if image_size is not None:
                image_width, image_height = image_size
                short_side_px = min(width * image_width, height * image_height)
                if short_side_px < min_box_px:
                    issues.append(
                        Issue(
                            check="label_format",
                            severity=WARN,
                            code="BOX_TINY",
                            image=image_stem,
                            message=f"box quá nhỏ: cạnh ngắn {short_side_px:.1f}px < {min_box_px}px",
                            line=line_number,
                            extra={"short_side_px": round(short_side_px, 2)},
                        )
                    )

            # 7. Cảnh báo box quá lớn (diện tích tỉ lệ > max_box_frac)
            area_fraction = width * height
            if area_fraction > max_box_frac:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=WARN,
                        code="BOX_HUGE",
                        image=image_stem,
                        message=f"box quá lớn: phủ {area_fraction * 100:.1f}% ảnh",
                        line=line_number,
                        extra={"area_frac": round(area_fraction, 4)},
                    )
                )

    return issues
