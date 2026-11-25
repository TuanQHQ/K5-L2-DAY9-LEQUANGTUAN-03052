# Báo cáo Day 09 — Le Quang Tuan-, 2A202603052

## 1. Kết luận trước
Pipeline kết luận **Hold** (mã thoát 10). Lô có **224 ảnh**. Cửa vào loại **22 ảnh**, còn **202/224 ảnh** được giữ và xuất ra `export/clean_v1`. Đây chỉ là bản nháp, **chưa phát hành**.

Lý do: sau khi máy sửa và người duyệt 80/80 ảnh, không còn lỗi bắt buộc nào. Tuy vậy, **38/202 ảnh (18.8%)** vẫn còn cảnh báo chưa có người duyệt, vượt ngưỡng 10% của cổng.

## 2. Lỗi và phân việc
Số liệu lấy từ `02_error_list_v1.csv`. Ô "x dòng / y ảnh" nghĩa là y ảnh, với tổng cộng x dòng lỗi.

| Mã lỗi | Số dòng / ảnh | Ai sửa | Vì sao |
|---|---:|---|---|
| CORRUPT_IMAGE | 2 / 2 | máy (loại ảnh) | ảnh không mở được, không cứu được |
| BAD_SIZE | 3 / 3 | máy (loại ảnh) | cạnh ngắn < 250px, sai quy tắc dự án |
| DUP_IMAGE_EXACT | 8 / 8 | máy (loại ảnh) | trùng từng byte, giữ một bản là đủ |
| DUP_IMAGE_NEAR | 4 / 4 | máy (loại ảnh) | trùng gần đúng (phash ≤ 12), gây lệch phân bố |
| LEAK_TEST | 5 / 5 | máy (loại ảnh) | trùng ảnh trong kho test, giữ lại sẽ làm mAP ảo |
| BAD_CLASS_NAME | 2 / 1 (`data.yaml`) | máy (`rename_classes`) | chỉ sai hoa/thường (`Person`, `Bus`), ánh xạ được chắc chắn |
| BAD_CLASS_ID | 6 / 6 | máy (`drop_line`) và người xem lại | ID 93/7/4/-1 không đoán được lớp đúng nên bỏ dòng (`FIXED_DROP_LINE` có trọng số 2 để người kiểm vật bị mất) |
| BAD_FORMAT | 3 / 3 | máy (`drop_line`) | NaN/inf hoặc thiếu cột, dòng này vô nghĩa |
| BOX_ZERO | 4 / 4 | máy (`drop_line`) | box có w hoặc h bằng 0 |
| DUP_BOX | 7 / 7 | máy (`drop_line`) | IoU ≥ 0.9 với box cùng lớp, chỉ là dòng lặp |
| BOX_OUT_OF_IMAGE | 8 / 8 | máy (`clip_box`) | tràn 2–6% khung ảnh, cắt về biên là an toàn |
| MISSING_LABEL_FILE | 6 / 6 | **người** (`NEEDS_LABEL`) | máy không được bịa nhãn, ảnh phải chờ người gán |
| EMPTY_LABEL | 12 / 12 (lên 15 ở v2) | người | có thể là ảnh nền hoặc thiếu nhãn, chỉ người phân biệt được |
| BOX_TINY / BOX_HUGE | 6 / 4 · 3 / 3 | người | đây là cảnh báo theo quy tắc, có thể đúng |
| POSSIBLE_MISSING | 53 / 52 | người | model nghi thiếu box (lỗi ngữ nghĩa) |
| POSSIBLE_WRONG_CLASS | 18 / 18 | người | nghi sai lớp (lỗi ngữ nghĩa) |
| POSSIBLE_FALSE_POS | 29 / 27 | người | nghi box thừa (lỗi ngữ nghĩa) |
| POSSIBLE_LOOSE_BOX | 28 / 24 | người | nghi box lỏng (lỗi ngữ nghĩa) |

Máy tự sửa 35 thay đổi (`03_fixes.csv`): 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`.

**Thứ tự hàng đợi.** `05_review_queue.csv` có 125 ảnh. Mỗi ảnh có điểm ưu tiên bằng tổng trọng số các mã lỗi của nó:
- `img_0020` đứng đầu (11.5 điểm) vì cùng lúc có `FIXED_DROP_LINE`, `POSSIBLE_MISSING` và `POSSIBLE_WRONG_CLASS`.
- Tiếp theo là 6 ảnh `NEEDS_LABEL` (10 điểm). Nếu thiếu các ảnh này, cổng sẽ ra Rework.
- Sau đó là các ảnh có nhiều mã ngữ nghĩa nặng (WRONG_CLASS = 3, MISSING/FALSE_POS = 2).
- Ảnh chỉ có cảnh báo nhẹ (BOX_TINY = 0.3, LOOSE_BOX = 1.5) xếp cuối.

**Với ngân sách 80 ảnh.** Ngưỡng ưu tiên của ảnh cuối cùng được duyệt là 3.34. Người duyệt đã xem:
- **18/18** ảnh WRONG_CLASS, **50/52** ảnh MISSING, **12/23** ảnh FALSE_POS và **8/24** ảnh LOOSE_BOX;
- cả 6 ảnh NEEDS_LABEL.

Tổng cộng có 88 lượt mã ngữ nghĩa được xem. Những gì còn sót chủ yếu là FALSE_POS và LOOSE_BOX, đúng với thứ tự trọng số đã đặt.

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | **12** | NEAR: 1.00/0.50 → 1.00/0.67 (EXACT giữ 1.00/1.00) | Trên calib, mọi giá trị từ 4 đến 14 cho cùng P/R. Ở 16, recall lên 0.83, nhưng trên lô thật lại loại nhầm ảnh khác nhau (xem bên dưới). Mình chọn 12 vì nó nằm giữa cặp trùng thật xa nhất (10) và cặp loại nhầm gần nhất (16). |
| `second_opinion.conf` | 0.25 | **0.6** | WRONG_CLASS: 0.56/0.83 → 0.62/0.83; MISSING: 0.50/1.00 → 0.57/1.00; LOOSE_BOX: 0.29/0.40 → 0.20/0.20 | Đây là giá trị cao nhất mà recall của MISSING vẫn là 1.00 (lên 0.7 thì recall tụt còn 0.88). Precision tăng, nên người duyệt bớt phải xem cảnh báo giả. Cái giá phải trả là LOOSE_BOX bắt kém hơn, nhưng lỗi này có trọng số thấp nhất trong nhóm ngữ nghĩa. FALSE_POS không đổi vì dùng `fp_conf` cố định. |

**Một chỗ calibration có thể đánh lừa.** Tập calib chỉ có 6 ảnh trùng gần đúng nên đường P/R gần như phẳng. Nhìn vào đó, `phash_dist = 8` (lựa chọn đầu tiên của mình) trông không khác gì 12. Mình tính phash cho mọi cặp trong 224 ảnh của lô thật, rồi mở ảnh ra xem:
- **10 — `img_0061` / `img_0186`**: cùng ảnh người ngồi ghế đá, chỉ khác màu và cắt nhẹ, tức là **trùng thật**. Với ngưỡng 8, cặp này lọt vào dataset.
- **16 — `img_0074` / `img_0084`**: cùng ảnh người cầm ô, chỉ bị cắt khác nhau, nên cũng là trùng.
- **16 — `img_0008` / `img_0011`**: ảnh trượt tuyết và ảnh tennis, **khác hẳn nhau**. Nếu chọn 16 (giá trị có F1 tốt nhất trên calib) thì cặp này bị loại nhầm.

Như vậy F1 trên 39 ảnh calib không chọn đúng ngưỡng cho lô thật. Phải nhìn vào phân bố khoảng cách của lô thật mới thấy. Từ 18 trở lên, số cặp tăng vọt (27 cặp ở 18, 95 cặp ở 20), nên số ảnh bị loại vì trùng (4) ở ngưỡng 12 là hợp lý.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Cổng chặn đúng.** Mình chạy:

```
python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb
```

Kết quả là `kết luận: REWORK — Còn 6 lỗi bắt buộc chưa được xử lý`, **mã thoát 20**, log in `Bước 5/5 KHÔNG xuất`, và thư mục `work/exp_nb` **không được tạo**. Không có người duyệt thì 6 ảnh `MISSING_LABEL_FILE` vẫn còn đó, và cổng không cho xuất. Khi có ngân sách 80, cả 6 ảnh được gán nên lỗi bắt buộc về 0, kết luận chỉ còn Hold.

**(b) Điểm mù có bằng chứng.**
1. **Ảnh trùng bị biến đổi mạnh.** `img_0074` và `img_0084` (phash 16, chỉ là hai cách cắt của cùng một ảnh) đều có trong `export/clean_v1`. Nâng ngưỡng để bắt cặp này thì sẽ loại nhầm `img_0008`/`img_0011`. Phash một mức không tách được hai trường hợp, cần thêm đặc trưng khác (embedding hoặc so khớp đặc trưng cục bộ).
2. **Box lỏng nhẹ.** Calib chèn box phóng to ×1.45–1.58. Ở conf 0.6, LOOSE_BOX chỉ có recall **0.20** (1/5) và precision 0.20. Box lỏng ít hơn mức đó gần như chắc chắn lọt. Ngoài ra còn 20 cảnh báo LOOSE_BOX trên 20 ảnh chưa có ai xem.
3. **Nhầm lớp mà model lớn cũng nhầm.** WRONG_CLASS trên calib chỉ có recall 0.83: 1/6 lỗi chèn bị bỏ sót vì yolo26l đồng ý với nhãn sai.
4. **FALSE_POS gần như vô dụng để phân loại.** Precision chỉ **0.31** (11 FP / 16 cảnh báo trên calib). Đây là nhóm cảnh báo còn tồn nhiều nhất ở v3 (21 ảnh) và là lý do chính khiến kết quả là Hold.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
**Cấu hình.** Model khởi tạo `yolo26n.pt`, 20 epoch, imgsz 640, batch 16, seed 0 và 1. Train trên Colab T4. Val là `gold_val` (40 ảnh), test là `data/test` (100 ảnh). Nguồn số liệu: `submission/results/comparison.md`.

| biến thể | #ảnh train | số seed | map50 (TB ± độ lệch) | map50_95 (TB ± độ lệch) | precision (TB ± độ lệch) | recall (TB ± độ lệch) |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 202 | 2 | 0.701 ± 0.025 | 0.487 ± 0.008 | 0.759 ± 0.003 | 0.625 ± 0.019 |

Chênh mAP50 (clean − raw) = **−0.025**.

Cột "#ảnh train" của `raw` ghi 224, nhưng Ultralytics thực tế bỏ **11 ảnh "corrupt"** (log bước 6: `216 images, 19 backgrounds, 11 corrupt`). Đó là 2 ảnh hỏng (`img_0010`, `img_0136`), 6 ảnh có ID lớp sai (93/7/4/−1) và 3 ảnh có tọa độ NaN hoặc sai số cột. Mỗi ảnh này bị bỏ cả ảnh, kể cả các box đúng trong đó. Vậy `raw` thật ra chỉ train trên **213 ảnh**, và đã được Ultralytics "lọc thô" một phần.

**AP50 theo lớp** (trung bình 2 seed):

| lớp | raw | clean | chênh |
|---|---:|---:|---:|
| car | 0.738 | 0.738 | 0.000 |
| person | 0.822 | 0.823 | +0.001 |
| truck | 0.648 | 0.538 | **−0.110** |
| bus | 0.695 | 0.703 | +0.008 |

**Kết luận (trung thực): chưa kết luận được** là clean tốt hơn hay kém hơn raw.
- Mức chênh −0.025 đúng bằng **1 độ lệch chuẩn giữa các seed** của `clean` (0.025), và chỉ đo trên 2 seed.
- Độ lệch ≈ 0 của `raw` là do tình cờ 2 seed cho cùng điểm, không có nghĩa là raw ổn định. Seed 1 của clean tự nó đã dao động 0.035 so với seed 0.
- Car, person và bus gần như không đổi (|Δ| ≤ 0.01). **Gần như toàn bộ mức chênh nằm ở lớp truck**: −0.110 / 4 lớp ≈ −0.028, xấp xỉ đúng bằng −0.025.
- Ngay trong `clean`, truck dao động 0.590 ↔ 0.486 giữa 2 seed (0.10), lớn hơn cả khoảng cách raw–clean ở các lớp khác.

**Giả thuyết và cách kiểm:**
1. **Rò rỉ test làm điểm `raw` cao lên.** `raw` vẫn chứa 5 ảnh trùng hệt ảnh test (`LEAK_TEST` trong `01_intake`: test_009/033/039/044/085), tức model raw đã "thấy" 5% tập test. *Cách kiểm:* đánh giá lại cả 2 model trên test sau khi bỏ 5 ảnh này. Hoặc train `raw` với đúng 5 ảnh rò rỉ bị bỏ ra (mọi thứ khác giữ nguyên) để tách riêng ảnh hưởng.
2. **Lớp truck quá ít mẫu, nên mức chênh là nhiễu.** Truck chỉ có 32 box (raw) và 41 box (clean) trên khoảng 750 box, trong khi tập test chỉ có 100 ảnh. Vài ảnh truck đúng hoặc sai là đủ làm AP đổi 0.1, như chính 2 seed của clean cho thấy. *Cách kiểm:* chạy ≥ 5 seed và đếm số truck trong test. Nếu khoảng tin cậy của truck chồng lên nhau thì kết luận là nhiễu.
3. **Nhãn truck/bus trong `clean` lệch quy ước so với test.** Sau autofix và review, số box đổi đáng kể: car 122→101, person 537→574, truck 32→41, bus 35→32. Truck tăng nhưng AP truck lại giảm, nên có thể một số box đã được đổi sang truck (hoặc giữ là truck) theo quy ước khác với người gán test. Nhầm truck↔bus cũng là nhóm `POSSIBLE_WRONG_CLASS` mà pipeline không chắc chắn được (mục 4). *Cách kiểm:* so confusion matrix truck/bus của 2 model trên test, và mở xem các ảnh trong `06_review_log` có thay đổi box truck/bus.
4. **`clean` chưa thật sự sạch.** Lô đang ở trạng thái Hold, còn 38 ảnh có cảnh báo ngữ nghĩa chưa có người duyệt, và 20 dòng bị `drop_line` có thể là vật thật bị mất nhãn. Vì vậy đây chưa phải chặn trên của "dữ liệu sạch". *Cách kiểm:* thêm biến thể `oracle` (nhãn người) vào notebook để có chặn trên.

Vì vậy kết quả train **không** chứng minh pipeline làm dataset tốt hơn, nhưng cũng không chứng minh làm tệ đi. Lợi ích rõ ràng của pipeline nằm ở **tính hợp lệ của phép đo**: bỏ 5 ảnh rò rỉ test và 12 ảnh trùng. Lợi ích này không hiện ra trên mAP, vì chính sự rò rỉ có thể đang thổi phồng điểm của `raw`.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối: Hold.** Dataset `clean_v1` (202 ảnh) chỉ dùng để thử nghiệm, chưa phát hành.

Để thành Release cần đưa số ảnh còn cảnh báo chưa duyệt xuống ≤ 20/202 (dưới 10%), tức là duyệt thêm ít nhất **18** trong 38 ảnh còn lại. Thực tế là nâng ngân sách lên khoảng 100 ảnh. Nên ưu tiên 19 ảnh chỉ có FALSE_POS và 18 ảnh chỉ có LOOSE_BOX. Hai nhóm này rẻ để xem vì mỗi ảnh chỉ có một box nghi vấn.

Mình không hạ ngưỡng cổng, và không vặn `conf` lên 0.8 chỉ để giảm số cảnh báo. Làm vậy sẽ hạ recall của MISSING xuống 0.75, tức là che lỗi đi chứ không sửa được lỗi.

**(b) Dùng AI.**
- *Prompt chính:* nhờ Claude Code (trợ lý lập trình) viết từng module check/autofix/gate/second_opinion theo docstring và test có sẵn. Sau đó nhờ nó đọc báo cáo, tính lại phash trên lô thật và soạn báo cáo này.
- *Cách kiểm:* chạy `pytest` (79 test pass), chạy `make calibrate` / `make run`, đối chiếu số trong báo cáo với `reports/*.csv`, và tự mở ảnh để kiểm các cặp trùng.
- *Một lần AI sai:* ngưỡng `phash_dist = 8` ban đầu được chọn chỉ dựa trên sweep calib. Khi mở ảnh lô thật mới thấy cặp `img_0061`/`img_0186` (khoảng cách 10) bị lọt, nên mình sửa ngưỡng lên 12.
