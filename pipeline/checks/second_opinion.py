"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    """So sánh nhãn với dự đoán của model lớn hơn để phát hiện các nghi ngờ lỗi ngữ nghĩa (WARN)."""
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg["second_opinion"]
    conf_threshold = so_cfg["conf"]
    min_area_px = so_cfg["min_area_px"]
    fp_conf_threshold = so_cfg["fp_conf"]
    iou_missing = so_cfg["iou_missing"]
    iou_match = so_cfg["iou_match"]
    iou_loose = so_cfg["iou_loose"]
    num_classes = len(ds.classes)

    issues = []

    for image_path in ds.image_files():
        image_stem = image_path.stem

        # Bỏ qua ảnh không có dự đoán hoặc chưa có file nhãn
        if image_stem not in preds:
            continue
        label_lines = ds.read_label_lines(image_stem)
        if label_lines is None:
            continue
        image_size = ds.image_size(image_stem)
        if image_size is None:
            continue

        image_width, image_height = image_size
        raw_predictions = preds[image_stem]

        # Đọc các dòng nhãn hợp lệ nhưng vẫn giữ nguyên số dòng gốc (1-based)
        valid_labels = []
        for line_number, line_text in label_lines:
            try:
                class_id, cx, cy, w, h = parse_yolo_line(line_text)
            except ValueError:
                continue
            if 0 <= class_id < num_classes:
                valid_labels.append((line_number, class_id, (cx, cy, w, h)))

        # Phần 1: Duyệt từng dự đoán đủ tự tin và đủ diện tích theo đúng thứ tự trong preds[stem]
        for prediction in raw_predictions:
            pred_class = int(prediction[0])
            pred_conf = float(prediction[1])
            pred_box = (
                float(prediction[2]),
                float(prediction[3]),
                float(prediction[4]),
                float(prediction[5]),
            )

            if pred_conf < conf_threshold:
                continue

            pred_area_px = (pred_box[2] * image_width) * (pred_box[3] * image_height)
            if pred_area_px < min_area_px:
                continue

            # Tìm tất cả nhãn (mọi lớp) có IoU >= iou_missing với dự đoán hiện tại
            candidates = []
            for _, label_class, label_box in valid_labels:
                overlap_iou = iou_xywh(pred_box, label_box)
                if overlap_iou >= iou_missing:
                    candidates.append((label_class, overlap_iou))

            # (1) Không khớp nhãn nào -> nghi ngờ thiếu nhãn
            if not candidates:
                issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_MISSING",
                        image=image_stem,
                        message=(
                            f"model phát hiện lớp {pred_class} (conf={pred_conf:.2f}) "
                            f"nhưng nhãn không có box khớp"
                        ),
                        extra={"conf": round(pred_conf, 4), "pred_class": pred_class},
                    )
                )
                continue

            # (2) Có ít nhất 1 nhãn cùng lớp -> xét box cùng lớp khớp tốt nhất
            same_class_ious = [
                overlap_iou for label_class, overlap_iou in candidates if label_class == pred_class
            ]
            if same_class_ious:
                best_same_iou = max(same_class_ious)
                if best_same_iou < iou_loose:
                    issues.append(
                        Issue(
                            check="second_opinion",
                            severity=WARN,
                            code="POSSIBLE_LOOSE_BOX",
                            image=image_stem,
                            message=(
                                f"box cùng lớp {pred_class} bị lệch/lỏng "
                                f"(IoU={best_same_iou:.2f} < {iou_loose})"
                            ),
                            extra={
                                "conf": round(pred_conf, 4),
                                "iou": round(best_same_iou, 4),
                                "pred_class": pred_class,
                            },
                        )
                    )
                # Nếu best_same_iou >= iou_loose thì nhãn đã phủ tốt vật thể -> không cảnh báo
                continue

            # (3) Không có nhãn cùng lớp -> xét box khác lớp khớp tốt nhất
            best_other_class, best_other_iou = max(candidates, key=lambda item: item[1])
            if best_other_iou >= iou_match:
                issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_WRONG_CLASS",
                        image=image_stem,
                        message=(
                            f"nghi ngờ gán nhầm lớp: nhãn={best_other_class}, "
                            f"model={pred_class} (conf={pred_conf:.2f}, IoU={best_other_iou:.2f})"
                        ),
                        extra={
                            "conf": round(pred_conf, 4),
                            "iou": round(best_other_iou, 4),
                            "label_class": best_other_class,
                            "pred_class": pred_class,
                        },
                    )
                )
            # Nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> mơ hồ, không báo

        # Phần 2: Kiểm tra từng dòng nhãn hợp lệ xem có bị thừa (POSSIBLE_FALSE_POS) hay không
        # Lọc dự đoán bằng fp_conf (không lọc theo min_area_px)
        fp_pred_boxes = []
        for prediction in raw_predictions:
            if float(prediction[1]) >= fp_conf_threshold:
                fp_pred_boxes.append(
                    (
                        float(prediction[2]),
                        float(prediction[3]),
                        float(prediction[4]),
                        float(prediction[5]),
                    )
                )

        for line_number, label_class, label_box in valid_labels:
            has_matching_prediction = False
            for pred_box in fp_pred_boxes:
                if iou_xywh(label_box, pred_box) >= iou_missing:
                    has_matching_prediction = True
                    break

            if not has_matching_prediction:
                issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_FALSE_POS",
                        image=image_stem,
                        message=(
                            f"dòng {line_number} (lớp {label_class}) không khớp dự đoán nào "
                            f"của model (conf >= {fp_conf_threshold})"
                        ),
                        line=line_number,
                        extra={"label_class": label_class},
                    )
                )

    return issues
