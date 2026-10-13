# NimbusAI GPU FinOps — Bài viết ngắn (Lab 25)

Mọi số liệu dưới đây lấy từ `python missions/run_all.py` và `outputs/report.md` (dữ liệu seed=25, kỳ tính theo tháng 30 ngày, trừ M6 dùng số ngày thực tế của job).

## 1. Baseline vs. Optimized

| Chỉ số | Baseline | Optimized | Thay đổi |
|---|---|---|---|
| Chi phí/tháng (GPU fleet + inference API) | $27,133 | $14,826 | −$12,307 (**45.4%**) |
| Inference $/1M-token | $6.488 | $1.126 | −82.6% |
| Inference $/ngày (2,400 request, 7.53M token) | $48.87 | $8.48 | −82.6% |
| GPU fleet/tháng (M3) | $25,667 on-demand | $15,971 | −37.8% |

## 2. Phân tích từng đòn bẩy

| Đòn bẩy | Tiết kiệm/tháng | Tỷ trọng trong tổng savings |
|---|---|---|
| Purchasing (spot/reserved) | $9,696 | 78.8% |
| Inference (cascade/cache/batch) | $1,212 | 9.8% |
| Right-size GPU memory-bound | $799 | 6.5% |
| Tắt GPU idle | $600 | 4.9% |

**Purchasing đóng góp nhiều nhất** vì riêng hóa đơn GPU fleet đã là $25,667/tháng, tức 94.6% baseline. Trong khi đó inference API chỉ tốn $1,466/tháng. Đòn bẩy nào tác động lên khoản lớn nhất thì mang lại nhiều USD nhất, kể cả khi % giảm của nó thấp hơn. Inference giảm tới 82.6% nhưng chỉ tính trên $1.5k. Purchasing giảm 37.8% nhưng tính trên $25.7k.

Trong 82.6% savings của inference, mình tính tuần tự từng bước:
- **Cascade đóng góp 76.5 điểm %**: 1,902/2,400 request (79%) được chuyển sang model nhỏ. Giá input của model nhỏ rẻ hơn 15 lần, giá output rẻ hơn 37.5 lần.
- Batch đóng góp 3.7 điểm.
- Cache chỉ đóng góp 2.4 điểm, vì cache chỉ giảm giá phần input, mà phần input của model nhỏ vốn đã rẻ.

Kết luận: phải **chọn đúng model trước**, sau đó mới áp chiết khấu.

## 3. GPU-Util Lie

M1 đánh dấu hai GPU có util ≥90% nhưng MFU <0.30:

| GPU | util% | MFU | MBU |
|---|---|---|---|
| **gpu-h100-4** | 98.2% | 0.194 | 0.207 |
| **gpu-a10g-1** | 96.9% | 0.268 | 0.302 |

**Cơ chế:** `nvidia-smi` chỉ đo tỷ lệ thời gian có ít nhất một kernel đang chạy. Nó không đo số FLOPs tạo ra. Một GPU có thể báo bận gần như suốt thời gian, trong khi SM thực ra đang:
- chờ dữ liệu từ HBM (memory stall),
- chạy các kernel nhỏ có overhead launch lớn,
- hoặc chờ dataloader hay giao tiếp giữa các GPU.

Dù vậy, hóa đơn vẫn tính theo giờ. gpu-h100-4 tốn $2.5 × 720h = $1,800/tháng nhưng chỉ dùng khoảng 19% FLOPs đỉnh, nghĩa là khoảng 4/5 số tiền mua compute bị bỏ phí.

**Tác động tài chính:** hai GPU này có thể right-size (đã kiểm tra dung lượng):
- gpu-h100-4 chuyển sang A100: $511/tháng.
- gpu-a10g-1 chuyển sang L4: $144/tháng.

Nếu chỉ nhìn util% thì đội vận hành sẽ còn **mua thêm** GPU, vì tưởng fleet đã chạy hết công suất.

## 4. Phần mở rộng đã làm (3 extension)

**Ext 1: `recommend_tier()`** (`finops/pricing.py`, `missions/m3_purchasing.py`)

Policy mới thêm bốn yếu tố:
- Interruption rate của spot theo từng loại GPU (giả định, ghi trong code): H100 5%/h, A100 7%, L4 10%, A10G 12%. Rate vượt 15% thì không chọn spot.
- Không cam kết reserved cho job ngắn hơn 30 ngày.
- Chọn reserved 1yr hay 3yr theo *effective rate* trong vòng đời dịch vụ.
- Tính commitment 24h/ngày, vì tiền reserved trả theo giờ cam kết chứ không theo giờ dùng.

Kết quả: **savings_pct giảm từ 39.1% xuống 37.8%** (chi phí tối ưu từ $15,627 lên $15,971/tháng). Không job nào đổi tier, nhưng chi phí được tính đúng hơn:
- job-infer-search (L4, 18h/ngày) tăng từ $972 lên $1,296. Policy cũ chỉ tính 18h trong khi commitment phải trả đủ 24h. Dù vậy 3yr vẫn rẻ hơn on-demand ($1,728).
- Spot A100/A10G đắt hơn một chút do phải làm lại nhiều hơn: job-train-embed $1,393 → $1,406, job-dev-sandbox $203 → $209.

Phân tích độ nhạy cho thấy quyết định phụ thuộc mạnh vào giả định vòng đời. Nếu fleet chỉ dùng 24 tháng thì 1yr thắng: savings giảm còn **29.4%** ($18,131/tháng), và L4 18h/ngày hòa vốn với on-demand.

**Insight:** savings % của policy cũ bị *thổi phồng* do tính reserved theo giờ dùng. Ngoài ra, cam kết 3yr chỉ đáng khi chắc chắn giữ loại GPU đó ≥36 tháng. `report.md` có thêm bảng matrix GPU × duty cycle × interruptible.

**Ext 2: Right-sizing theo MBU** (`finops/rightsizing.py`, `missions/m1_efficiency_audit.py`)

Cách làm:
1. Xác định GPU memory-bound theo roofline: FLOP/byte của workload thấp hơn ridge point của GPU.
2. Chọn GPU NVIDIA rẻ nhất vẫn chứa được peak VRAM ×1.1 và peak bandwidth/TFLOPs ×1.2.

Kết quả: **$799/tháng**, so với $655 nếu dùng bảng hạ một bậc "mù" của M5 gốc:
- gpu-h100-4 chuyển sang A100: $511.
- gpu-a10g-0 và gpu-a10g-1 chuyển sang L4: $144 mỗi GPU.

M5 nay dùng con số đã kiểm tra dung lượng này cho lever right-size.

**Insight, cũng là câu trả lời cho "vì sao không chọn GPU rẻ nhất theo $/hr":**
- Hai A100 inference dùng tới 67GB VRAM (cần 74GB tính cả headroom), nên L4/A10G 24GB không chứa nổi. Ràng buộc chặn ở đây là VRAM, không phải giá.
- Các H100 training cần khoảng 2.1TB/s và 485 TFLOPs, nên không GPU NVIDIA rẻ hơn nào đáp ứng được.
- Theo $/GB-VRAM, MI300X rẻ nhất ($0.0102/GB-h). Gộp 2×A100 vào 1×MI300X 192GB sẽ tiết kiệm **$1,174/tháng**. Phương án này chưa tính vào tổng vì phải port sang ROCm.

**Giới hạn:** chưa có benchmark throughput. Bandwidth đỉnh thấp hơn (L4 0.3TB/s) có thể làm tăng latency, nên cần load test trước khi chuyển.

**Ext 5: Carbon-aware scheduling** (`missions/m6_carbon_scheduling.py`, `finops/sustainability.py`)

Phạm vi: 5 job interruptible. Năng lượng = TDP × số GPU × giờ/ngày × **số ngày thực tế**, tổng 1,789.0 kWh.

Chuyển từ us-east-1 sang europe-north1:
- Carbon: **679.8 → 53.7 kgCO2e (−626,150 g, −92.1%)**.
- Tiền điện cũng giảm: $214.68 → $161.01.

Vùng rẻ nhất và vùng sạch nhất **khác nhau**:
- Rẻ nhất (cũng là vùng cân bằng 50/50): us-east-wa, $98.39 tiền điện, 161.0 kg.
- Sạch nhất: europe-north1.
- Chọn sạch nhất thay vì rẻ nhất tốn thêm khoảng **$583 cho mỗi tấn CO2e** giảm được.

**Insight:** vùng "tối ưu" tùy vào ưu tiên của công ty (chi phí hay mục tiêu carbon) và vào latency/data residency. Chỉ nên chuyển các job training/batch chịu được gián đoạn. Inference cần latency thấp thì giữ gần người dùng.

## 5. Khuyến nghị cho NimbusAI (3 việc đầu tiên, theo ROI)

1. **Chốt chiến lược mua GPU** (khoảng $9.7k/tháng, chiếm 79% savings):
   - Chạy training và dev trên spot có checkpoint.
   - Mua reserved 3yr cho baseline inference 24/7 *sau khi* xác nhận lộ trình ≥36 tháng. Nếu không chắc thì chọn 1yr và chấp nhận savings khoảng 29%.
2. **Quick win về hiệu suất** ($1,399/tháng, rủi ro thấp):
   - Tắt GPU idle ($600/tháng; gpu-h100-5 có 8h idle mỗi ngày).
   - Right-size gpu-h100-4 sang A100 và 2 A10G sang L4 ($799/tháng), sau khi load test.
   - Theo dõi MFU/MBU trên dashboard thay cho GPU-Util%.
3. **Quản trị bằng đơn vị và trách nhiệm:**
   - Bắt buộc cascade routing, vì đây là lever giảm $/1M-token từ $6.488 xuống $1.126.
   - Bật chargeback theo team: tag coverage đã đạt 92%, trên ngưỡng 80%.
   - Đặt job training interruptible vào europe-north1 hoặc us-east-wa để giảm tới 92% CO2e mà không tăng tiền điện.
