"""BƯỚC 4 — Cửa chặn: quyết định Release / Hold / Rework.   ★

Test:  pytest tests/test_gate.py -q

Cây quyết định Day 07 (slide Day 09: "Lỗi bắt buộc chặn pipeline; lỗi cảnh báo chuyển người xem"):

  còn ≥ 1 lỗi bắt buộc (severity ERROR)                          -> "Rework"
  không còn lỗi bắt buộc, nhưng tỉ lệ ẢNH còn cảnh báo
      >= cfg["gate"]["warn_ratio_hold"]                          -> "Hold"
  còn lại                                                        -> "Release"

Tỉ lệ cảnh báo = (số ẢNH khác nhau có ≥ 1 cảnh báo) / (tổng số ảnh).  Chú ý:
- chỉ đếm issue có `image` nằm trong `image_stems` (bỏ "<dataset>", "data.yaml");
- bỏ qua ảnh nằm trong `reviewed` (người đã xem, cảnh báo của ảnh đó coi như đã xử lý) — nhưng LỖI BẮT BUỘC thì không bao giờ được bỏ qua;
- mẫu số là số ảnh, không phải số issue.

Trả về dict: decision, n_errors, n_warn_images, n_images, warn_ratio (làm tròn 4 chữ số), reasons (list[str], giải thích bằng tiếng Việt, có số liệu).
"""
from ..common import ERROR, WARN


def decide(issues, image_stems, cfg, reviewed=frozenset()):
    """Quyết định Release / Hold / Rework dựa trên lỗi bắt buộc và tỉ lệ ảnh còn cảnh báo."""
    warn_ratio_hold = cfg["gate"]["warn_ratio_hold"]
    valid_stems = set(image_stems)
    reviewed_stems = set(reviewed)
    n_images = len(valid_stems)

    # 1. Đếm toàn bộ lỗi bắt buộc (không bao giờ bỏ qua, kể cả ở ảnh đã duyệt)
    n_errors = 0
    for issue in issues:
        if issue.severity == ERROR:
            n_errors += 1

    # 2. Đếm số ẢNH khác nhau còn cảnh báo chưa được người duyệt
    warn_images = set()
    for issue in issues:
        if issue.severity != WARN:
            continue
        if issue.image not in valid_stems:
            continue
        if issue.image in reviewed_stems:
            continue
        warn_images.add(issue.image)

    n_warn_images = len(warn_images)

    # 3. Tính tỉ lệ ảnh còn cảnh báo (tránh chia cho 0 khi tập rỗng)
    if n_images > 0:
        raw_warn_ratio = n_warn_images / n_images
    else:
        raw_warn_ratio = 0.0
    warn_ratio = round(raw_warn_ratio, 4)

    # 4. Cây quyết định: Rework -> Hold -> Release
    if n_errors > 0:
        decision = "Rework"
        reasons = [
            f"Còn {n_errors} lỗi bắt buộc chưa được xử lý (cần sửa trước khi xuất dataset)."
        ]
    elif raw_warn_ratio >= warn_ratio_hold:
        decision = "Hold"
        reasons = [
            f"Không còn lỗi bắt buộc, nhưng tỉ lệ ảnh còn cảnh báo chưa duyệt là "
            f"{n_warn_images}/{n_images} ({warn_ratio * 100:.2f}% >= ngưỡng {warn_ratio_hold * 100:.2f}%)."
        ]
    else:
        decision = "Release"
        reasons = [
            f"Không còn lỗi bắt buộc; tỉ lệ ảnh còn cảnh báo chưa duyệt là "
            f"{n_warn_images}/{n_images} ({warn_ratio * 100:.2f}% < ngưỡng {warn_ratio_hold * 100:.2f}%)."
        ]

    return {
        "decision": decision,
        "n_errors": n_errors,
        "n_warn_images": n_warn_images,
        "n_images": n_images,
        "warn_ratio": warn_ratio,
        "reasons": reasons,
    }
