"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
REMOVE_IMAGE_CODES = {"CORRUPT_IMAGE", "BAD_SIZE", "LEAK_TEST"}


def _is_remove_image_code(code: str) -> bool:
    return code in REMOVE_IMAGE_CODES or code.startswith("DUP_IMAGE_")


def fix(ds, issues, cfg):
    """Sửa tự động các lỗi bắt buộc (ERROR) trên thư mục bản sao `ds` và trả về log thay đổi."""
    fixes = []

    images_to_remove = set()
    images_needing_label = set()
    need_rename_classes = False
    lines_to_drop = defaultdict(set)
    lines_to_clip = defaultdict(set)

    # 1. Phân loại các issue có mức độ ERROR (tuyệt đối không chạm vào WARN)
    for issue in issues:
        if issue.severity != ERROR:
            continue

        code = issue.code
        image_stem = issue.image

        if _is_remove_image_code(code):
            images_to_remove.add(image_stem)
        elif code == "BAD_CLASS_NAME":
            need_rename_classes = True
        elif code == "MISSING_LABEL_FILE":
            images_needing_label.add(image_stem)
        elif code in DROP_LINE_CODES and issue.line is not None:
            lines_to_drop[image_stem].add(issue.line)
        elif code == "BOX_OUT_OF_IMAGE" and issue.line is not None:
            lines_to_clip[image_stem].add(issue.line)

    # 2. Xoá ảnh lỗi nặng (hỏng, nhỏ, trùng, rò rỉ test) kèm file nhãn nếu có
    for image_stem in sorted(images_to_remove):
        image_path = ds.image_path(image_stem)
        label_path = ds.label_path(image_stem)
        removed_parts = []

        if image_path is not None and image_path.exists():
            image_path.unlink()
            removed_parts.append(image_path.name)

        if label_path.exists():
            label_path.unlink()
            removed_parts.append(label_path.name)

        if removed_parts:
            fixes.append(
                {
                    "image": image_stem,
                    "line": "",
                    "action": "remove_image",
                    "before": ", ".join(removed_parts),
                    "after": "(đã xoá)",
                }
            )

    # 3. Chuẩn hoá lại danh sách tên lớp trong data.yaml theo cfg["classes"]
    if need_rename_classes:
        before_names = ds.yaml_names()
        if ds.yaml_path.exists():
            yaml_data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        else:
            yaml_data = {}

        new_names = {index: class_name for index, class_name in enumerate(cfg["classes"])}
        yaml_data["names"] = new_names
        ds.yaml_path.write_text(
            yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        fixes.append(
            {
                "image": "data.yaml",
                "line": "",
                "action": "rename_classes",
                "before": str(before_names),
                "after": str(new_names),
            }
        )

    # 4. Ảnh thiếu file nhãn: KHÔNG tạo file rỗng, chỉ ghi log để chuyển người gán
    for image_stem in sorted(images_needing_label):
        if image_stem in images_to_remove:
            continue
        if ds.label_path(image_stem).exists():
            continue
        fixes.append(
            {
                "image": image_stem,
                "line": "",
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán",
            }
        )

    # 5. Sửa lỗi theo dòng cho từng file nhãn (gom theo file, ghi lại đúng 1 lần)
    affected_stems = sorted(set(lines_to_drop.keys()) | set(lines_to_clip.keys()))
    for image_stem in affected_stems:
        # Ảnh đã bị xoá ở bước 2 thì bỏ qua êm
        if image_stem in images_to_remove:
            continue

        label_path = ds.label_path(image_stem)
        if not label_path.exists():
            continue

        raw_lines = label_path.read_text(encoding="utf-8", errors="replace").splitlines()
        drop_set = lines_to_drop[image_stem]
        clip_set = lines_to_clip[image_stem]

        updated_lines = []
        file_changed = False

        for line_number, raw_line in enumerate(raw_lines, start=1):
            # Nếu dòng vừa cần xoá vừa cần cắt -> ưu tiên xoá dòng (không ghi clip_box)
            if line_number in drop_set:
                file_changed = True
                fixes.append(
                    {
                        "image": image_stem,
                        "line": line_number,
                        "action": "drop_line",
                        "before": raw_line,
                        "after": "(đã xoá dòng)",
                    }
                )
                continue

            if line_number in clip_set:
                file_changed = True
                try:
                    class_id, center_x, center_y, width, height = parse_yolo_line(raw_line)
                except ValueError:
                    fixes.append(
                        {
                            "image": image_stem,
                            "line": line_number,
                            "action": "drop_line",
                            "before": raw_line,
                            "after": "(đã xoá dòng hỏng)",
                        }
                    )
                    continue

                left = max(0.0, center_x - width / 2.0)
                right = min(1.0, center_x + width / 2.0)
                top = max(0.0, center_y - height / 2.0)
                bottom = min(1.0, center_y + height / 2.0)

                new_width = right - left
                new_height = bottom - top

                # Nếu sau khi cắt không còn diện tích (nằm hoàn toàn ngoài ảnh) -> xoá dòng
                if new_width <= 1e-6 or new_height <= 1e-6:
                    fixes.append(
                        {
                            "image": image_stem,
                            "line": line_number,
                            "action": "drop_line",
                            "before": raw_line,
                            "after": "(đã xoá: box nằm ngoài ảnh)",
                        }
                    )
                    continue

                new_center_x = (left + right) / 2.0
                new_center_y = (top + bottom) / 2.0
                clipped_line = (
                    f"{class_id} {new_center_x:.6f} {new_center_y:.6f} "
                    f"{new_width:.6f} {new_height:.6f}"
                )
                updated_lines.append(clipped_line)
                fixes.append(
                    {
                        "image": image_stem,
                        "line": line_number,
                        "action": "clip_box",
                        "before": raw_line,
                        "after": clipped_line,
                    }
                )
                continue

            # Dòng bình thường (bao gồm cả dòng trống) được giữ nguyên
            updated_lines.append(raw_line)

        if file_changed:
            if updated_lines:
                content = "\n".join(updated_lines) + "\n"
            else:
                content = ""
            label_path.write_text(content, encoding="utf-8")

    return fixes
