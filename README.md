# TI 2026 Match Predictor

Web app chạy **local** trên máy bạn: chọn 2 team dự The International 2026, chọn hero cho mỗi bên và
ai cầm hero nào, bấm **Dự đoán** → app đưa ra xác suất thắng và dự đoán over/under thời lượng trận
(mặc định 41 phút).

Dữ liệu được thu thập trực tiếp từ Liquipedia, GosuGamers và OpenDota rồi lưu vào SQLite trong thư
mục `data/`. Không có API key, không cần tài khoản, chạy hoàn toàn offline sau lần thu thập đầu.

---

## 1. Cài đặt & chạy

> **App là một server chạy trên máy bạn, không phải trang web sẵn có.**
> Mở `http://127.0.0.1:8000` mà chưa bật server thì trình duyệt sẽ báo không kết nối được.
> Phải chạy `run.bat` (hoặc shortcut) trước, và **giữ cửa sổ đen đó mở** suốt lúc dùng app.

### Bước 0: tải project về

Cần [Git](https://git-scm.com/download/win) và [Python 3.10+](https://www.python.org/downloads/)
(nhớ tick **"Add python.exe to PATH"** khi cài Python).

```bash
git clone https://github.com/Hayashin1471/dota2-ti2026-predictor.git
```

```bash
cd dota2-ti2026-predictor
```

### Cách dễ nhất: double-click `run.bat`

Mở thư mục vừa clone và double-click **`run.bat`**. Nó tự cài thư viện thiếu, tự thu thập dữ liệu
nếu chưa có (lần đầu ~10–15 phút, chỉ một lần), rồi tự mở trình duyệt khi server sẵn sàng.

Muốn có shortcut ngoài Desktop / Start Menu cho tiện:

```bash
powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1 -StartMenu
```

### Hoặc chạy bằng dòng lệnh

```bash
pip install -r requirements.txt
```

```bash
run.bat
```

Hoặc tách riêng từng bước:

```bash
python -m backend refresh all --drafts 600
```

```bash
python -m backend serve
```

Mở http://127.0.0.1:8000

> **Nên đặt email liên hệ của bạn** vào biến môi trường `DOTA_APP_CONTACT`. Điều khoản API của
> Liquipedia yêu cầu User-Agent có thông tin liên hệ. App vẫn chạy nếu không đặt, nhưng đặt thì
> lịch sự và an toàn hơn:
> ```bash
> set DOTA_APP_CONTACT=email-cua-ban@example.com
> ```

## 2. Cách dùng

1. Chọn **Team A** và **Team B** từ dropdown (danh sách 16 đội dự TI 2026 lấy từ Liquipedia).
   Mở dropdown là con trỏ nhảy thẳng vào ô tìm kiếm — gõ vài chữ để lọc theo **tên đội**
   (`x` → Xtreme Gaming, Team Yandex…), theo **tên tuyển thủ** (`yatoro` → Team Spirit), hoặc theo
   **suất tham dự** (`invite`, `europe`). Nhấn **Enter** để chọn kết quả đầu tiên.
2. Bấm vào các ô hero để chọn tối đa 5 hero mỗi bên. Có thể tìm theo tên hoặc lọc theo chỉ số chính.
   Bỏ trống cũng được — khi đó app chỉ dự đoán dựa trên sức mạnh đội.
3. Dưới mỗi ô hero là **tuyển thủ cầm hero đó**. Chọn đội xong app tự điền 5 người đang trong đội
   hình chính (theo thứ tự Carry → Mid → Offlane → Soft support → Hard support); bấm vào tên để đổi
   người, chọn "Không gán" nếu không muốn tính yếu tố này. Nếu ô đó đã có hero, danh sách hiện luôn
   *số trận và tỉ lệ thắng của từng tuyển thủ trên đúng hero đó* — tiện để xem ai mới là người quen
   tay với hero này.
4. Đổi mốc over/under nếu muốn (mặc định 41 phút).
5. Bấm **DỰ ĐOÁN**.
6. Bấm vào một trận trong "Lịch thi đấu TI 2026" để nạp nhanh 2 đội của trận đó.

Mục **Lịch sử kết quả** có 3 tab:

| Tab | Nội dung | Nguồn |
|---|---|---|
| **TI 2026** | Các series đã kết thúc của TI, kèm tỉ số | hawk.live |
| **2 đội đang chọn** | Từng ván của 2 đội, kèm thời lượng và nhãn O/U, cùng tỉ lệ % số ván vượt mốc | OpenDota |
| **Tất cả giải** | Series đã kết thúc ở mọi giải trong ~14 ngày | hawk.live |

Tab "2 đội đang chọn" là phần đối chiếu cho dự đoán O/U: nếu mô hình báo OVER mà 2 đội chỉ có 30%
số ván vượt mốc thì bạn biết ngay là nên nghi ngờ.

Nút **Cập nhật dữ liệu** ở góc phải chạy lại phần thu thập nhanh (giải đấu, đội, hero, lịch).

## 3. Nguồn dữ liệu

| Nguồn | Dùng để làm gì | Cách lấy |
|---|---|---|
| [Liquipedia](https://liquipedia.net/dota2/The_International/2026) | 16 đội tham dự, đội hình, thể thức, thời gian, patch | MediaWiki API `action=parse`, parse wikitext |
| [GosuGamers](https://www.gosugamers.net/dota2) | Lịch thi đấu / kết quả / trận đang live của TI 2026 | Scrape HTML |
| [hawk.live](https://hawk.live/dota-2/matches/results) | Kho kết quả series đã kết thúc, đánh chỉ mục theo ngày | Scrape HTML |
| [OpenDota](https://www.opendota.com) | Lịch sử trận pro (thời lượng, thắng thua), rating đội, danh sách + thống kê hero, draft từng trận | REST API công khai |

**Vì sao cần OpenDota:** Liquipedia và GosuGamers cho biết *ai* thi đấu và *khi nào*, nhưng không
công bố dữ liệu máy đọc được về thời lượng trận hay tỉ lệ thắng của từng hero. Đó chính là những con
số mô hình dự đoán cần, nên app bổ sung OpenDota (miễn phí, dựa trên dữ liệu trận của Valve).

App tôn trọng giới hạn của các bên: giãn cách request theo từng host (Liquipedia 2s, OpenDota ~1s),
gửi User-Agent mô tả rõ, dùng gzip theo yêu cầu của Liquipedia, và cache mọi response vào SQLite.

## 4. Mô hình dự đoán

### 4.1 Xác suất thắng

Bốn tín hiệu được cộng trên thang **log-odds**:

```
logit(P_A) = W_team · (R_A − R_B)·ln10/400  +  m_hero · W_hero · Σ Δlogit(winrate)
             +  m_matchup · W_matchup · Δ khắc chế
             +  W_player · Σ Δlogit(winrate của tuyển thủ trên hero được gán)
```

`m_hero` / `m_matchup` là **hiệu chỉnh theo giải**, học từ chính các ván TI 2026 đã đấu — xem mục
4.3. Trước khi giải khởi tranh cả hai bằng 1, tức công thức trở về đúng dạng cũ.

1. **Sức mạnh đội (Elo)** — chạy Elo trên toàn bộ trận pro của 16 đội trong ~21 tháng gần nhất
   (`ELO_HISTORY_DAYS`). Trận càng cũ hệ số K càng nhỏ (half-life 300 ngày); 10 trận đầu của một đội
   được cập nhật nhanh hơn. Kết quả được trộn với rating riêng của OpenDota, sau khi hồi quy tuyến
   tính đưa hai thang về cùng một hệ quy chiếu.
2. **Chất lượng hero** — tỉ lệ thắng của hero ở bracket cao (Divine+/Immortal), được kéo về phía mẫu
   pro mà app tự tải. Trọng số cố tình để thấp (`W_HERO_WINRATE = 0.30`): tỉ lệ thắng pro của một
   hero một phần phản ánh *đội nào pick nó*, mà sức mạnh đội đã là một số hạng riêng rồi.
3. **Khắc chế đội hình** — bảng đối đầu hero-vs-hero của OpenDota, tính theo *chênh lệch so với nền
   riêng của từng hero* để không đếm hai lần sức mạnh sẵn có của hero đó.
4. **Tuyển thủ với hero** — tỉ lệ thắng của đúng người đó trên đúng hero đó, đo **so với tỉ lệ
   thắng chung của chính họ**. Lấy con số thô sẽ chủ yếu đo lại "đội này mạnh", mà mục 1 đã đo rồi;
   phần dư ra chính là độ thuần thục hero. Ví dụ Yatoro có winrate chung 53% nhưng Morphling 60%
   (1.854 trận) → +0.279 log-odds, gần chạm trần `PLAYER_EDGE_CAP`.

Tổng đóng góp của draft bị chặn ở `DRAFT_LOGIT_CAP` để đội hình không lấn át sức mạnh đội, và số
hạng tuyển thủ bị chặn riêng ở `PLAYER_LOGIT_CAP`.

**Vì sao số hạng tuyển thủ được shrink mạnh:** record của một người trên một hero thường chỉ vài
chục trận. Nó được kéo về winrate chung của chính người đó với `PLAYER_HERO_PRIOR_GAMES = 45` trận
giả định, rồi cắt trần ở ±`PLAYER_EDGE_CAP`; dưới `PLAYER_MIN_GAMES = 3` trận thì coi như **không
có thông tin** (edge = 0) chứ không coi là yếu. Dữ liệu lấy từ toàn bộ trận OpenDota có của tuyển
thủ, **kể cả trận rank** — mẫu chỉ tính trận pro thì quá mỏng để nói được gì. Vì cả tử số lẫn mẫu số
đều là của cùng một người nên phần "pub dễ thắng hơn pro" tự triệt tiêu.

### 4.2 Over/Under thời lượng

Thời lượng trận được mô hình hoá **lognormal**:

```
μ = μ_nền(120 ngày gần nhất)  +  dịch chuyển meta  +  nhịp độ 2 đội  +  ảnh hưởng đội hình
    +  Δ_TI
P(over) = 1 − Φ( (ln(41·60) − μ) / σ )
```

- **μ_nền** lấy theo cửa sổ hẹp nhất còn đủ mẫu (mặc định 120 ngày). Điều này quan trọng: trung bình
  toàn bộ lịch sử trong DB là ~37 phút, nhưng pro Dota gần đây là **~41 phút** — đúng ngay mốc 41,
  nên mốc này thực sự cân bằng chứ không lệch hẳn về một phía.
- **Nhịp độ đội** đo trong cùng cửa sổ với mặt bằng chung, nên độ trôi theo patch không bị đếm hai lần.
- **Ảnh hưởng đội hình** cộng độ lệch log-thời-lượng của 10 hero được chọn, mỗi hero bị shrink theo
  `n/(n + DURATION_PRIOR_GAMES)`.
- **Δ_TI** là phần dư còn lại sau tất cả những thứ trên, đo trên chính các ván TI đã đấu — mục 4.3.

### 4.3 Hiệu chỉnh theo giải: học từ các ván TI đã đấu

Một ván TI **không phải** một ván pro trung bình, và điều đó chỉ đo được sau khi giải bắt đầu. Sau
2 ngày đầu (59 ván) dữ liệu nói hai điều rất rõ:

| Điều mô hình cũ giả định | Thực tế TI 2026 ngày 1–2 |
|---|---|
| Chênh lệch winrate nền giữa 2 draft là tín hiệu thật | Ở TI gần như **không** là tín hiệu |
| Thời lượng ván bằng mặt bằng pro gần đây | Dài hơn: trung vị **46,9′** vs 37,2′ của cả pool pro 120 ngày |

Chuyện winrate hero mất tác dụng ở TI là hợp lý khi nghĩ kỹ: `pub_winrate` đo hero mạnh yếu ra sao
*trong tay người chơi trung bình*. Ở TI, 16 đội đều bốc từ cùng một pool hero đã chuẩn bị kỹ, nên
một hero "winrate thấp" nằm trong draft của Falcons là một lựa chọn có tính toán, không phải một
pick tồi. Kiểm chứng bằng ablation (fit trên toàn bộ trận không phải TI, chấm trên 59 ván TI):

| Tổ hợp số hạng | Log-loss trên TI | Log-loss trên 450 trận pro khác |
|---|---|---|
| chỉ team | 0,6583 | 0,6690 |
| team + hero | 0,6740 | 0,6648 |
| team + khắc chế | **0,6408** | 0,6304 |
| team + hero + khắc chế (mô hình cũ) | 0,6650 | **0,6177** |

Thêm số hạng hero làm mô hình **tệ đi** trên TI (0,6583 → 0,6740) nhưng **tốt lên** ở giải khác —
tức đây là hiệu ứng riêng của TI, không phải lỗi chung. Bootstrap 3.000 lần trên 59 ván: tắt hẳn số
hạng hero cho kết quả tốt hơn trong **89,0%** lần lấy mẫu lại. Số hạng khắc chế thì ngược lại — chỉ
12,2%, nên nó được để gần như nguyên.

**Ba tham số, mỗi tham số một con số.** Đây là lý do 59 ván đủ dùng ở đây mà không đủ để fit lại
3 trọng số chính: mỗi hiệu chỉnh chỉ là *một* tham số và có sẵn một giá trị mặc định hiển nhiên
(nhân 1, cộng 0). Ước lượng thô rồi bị kéo về mặc định theo `n/(n + prior)`:

| Hiệu chỉnh | Ước lượng thô | Sau shrink (59 ván) | Prior |
|---|---|---|---|
| `hero_mult` | 0,00 | **0,50** | 60 ván |
| `matchup_mult` | 0,90 | **0,95** | 60 ván |
| `duration_shift` | +0,068 log (se 0,036) | **+0,045 log** ≈ +4,6% | 30 ván |

Dưới `TI_CONTEXT_MIN_GAMES = 20` ván thì **không hiệu chỉnh gì cả**. Càng nhiều ngày thi đấu, mẫu
càng lớn, shrink càng nhẹ — nếu xu hướng là thật nó sẽ mạnh dần, còn nếu 2 ngày đầu chỉ là nhiễu thì
ước lượng thô tự trôi về 1 và hiệu chỉnh tự tan.

**Đo thử out-of-sample thật sự** (fit hiệu chỉnh trên 29 ván ngày 1, chấm trên 30 ván ngày 2 — dữ
liệu mà nó chưa từng thấy):

| Chỉ số trên ngày 2 | Không hiệu chỉnh | Có hiệu chỉnh |
|---|---|---|
| Log-loss | 0,7381 | **0,7319** |
| Độ chính xác | 46,7% | **50,0%** |
| Độ chính xác O/U | 63,3% | **66,7%** |
| Brier O/U | 0,2232 | **0,2181** |

Tốt lên ở cả 4 chỉ số. Nhưng 30 ván thì khoảng tin cậy rất rộng — đây là *bằng chứng ủng hộ*, không
phải chứng minh. `python -m backend evaluate` in lại chính bảng này (`ti_context_holdout`) mỗi lần
chạy, nên sau mỗi ngày thi đấu bạn tự kiểm tra được hiệu chỉnh còn đứng vững hay không.

Áp lên cả 59 ván (in-sample cho hiệu chỉnh, nên coi là **cận trên**):

| Chỉ số trên 59 ván TI | Không hiệu chỉnh | Có hiệu chỉnh |
|---|---|---|
| Log-loss | 0,6632 | **0,6503** |
| Độ chính xác | 55,9% | 55,9% |
| Độ chính xác O/U | 67,8% | **72,9%** |
| Brier O/U | 0,2159 | **0,2061** |

Hiệu chỉnh **chỉ áp cho trận TI**. Backtest trên các giải khác không đổi một chữ số nào.

### 4.4 Fit trọng số & backtest

`python -m backend evaluate` chấm điểm mô hình trên chính dữ liệu đã tải:

- **Dataset**: mọi trận pro trong DB có đủ 10 pick.
- **Đặc trưng chống rò rỉ**: cột `matches.pre_elo_*` lưu Elo của 2 bên **trước** trận
  (ghi lại trong lúc chạy Elo), nên mô hình không nhìn thấy kết quả khi chấm chính nó.
- **Fit**: gradient ascent trên log-likelihood có phạt L2, cho 3 trọng số + 1 hệ số bias.
  Bias hấp thụ lợi thế phe Radiant — app không dùng nó (người dùng chọn đội chứ không chọn phe),
  nhưng bỏ nó ra thì lợi thế đó sẽ bị dồn nhầm vào 3 trọng số kia.
- **Chia dữ liệu theo thời gian**: fit trên 75% trận cũ, chấm trên 25% trận mới hơn.
- **Hai lần fit, hai mục đích khác nhau.** Lần fit theo lát cắt thời gian ở trên là để *đo* — nó là
  con số duy nhất nói được mô hình có tổng quát hoá hay không. Nhưng trọng số **được lưu** thì fit
  trên **toàn bộ** dữ liệu, kể cả 25% mới nhất và cả các ván TI: vứt đi đúng phần dữ liệu gần nhất
  với những trận sắp dự đoán là phí phạm. Trước đây app lưu bộ trọng số fit trên 75% cũ, tức bỏ
  không ~470 trận mới nhất.
- `--apply` lưu trọng số + hiệu chỉnh theo giải vào DB; `model.weights()` và `model.ti_context()`
  sẽ ưu tiên dùng chúng thay cho hằng số config.

**Vẫn không thể "train" 3 trọng số bằng vài ngày thi đấu.** 59 trận không đủ để xác định 3 tham số
tự do. Cái 59 trận đó *đủ* để làm là 3 hiệu chỉnh một-tham-số ở mục 4.3 — mỗi cái chỉ ước lượng một
con số quanh một giá trị mặc định đã biết trước.

**Vì sao số hạng hero dùng `pub_winrate` chứ không phải `winrate`:** `winrate` được kéo về phía
mẫu trận pro mà app tự tải — tức là **chính tập trận đang fit**. Dùng nó thì đặc trưng hero mang sẵn
kết quả nó phải dự đoán. Đo thử: mẫu pro trung vị 106 ván/hero, lệch trung bình 2 điểm % so với
`pub_winrate`, và số hạng hero khi đó đóng góp 0.487 logits — **lớn hơn cả sức mạnh đội (0.355)**,
điều vô lý với Dota chuyên nghiệp. Chuyển sang `pub_winrate` (chỉ từ trận public, độc lập hoàn toàn
với tập trận pro): đóng góp về 0.276 logits và log-loss trên test **tốt lên** (0.6291 → 0.6254).

Vẫn còn một điểm chưa xử lý được: bảng tỉ lệ thắng và bảng khắc chế là số liệu **của patch hiện tại**
áp lên các trận trong quá khứ. Đây không phải rò rỉ kết quả, nhưng vẫn là một dạng "nhìn trước" nhẹ.

### Kết quả đo thực tế

Dataset 2.168 trận (26/5 → 14/8/2026), fit trên 1.626 trận cũ, chấm trên 542 trận mới hơn:

| Chỉ số | Trọng số đã fit | Trọng số config cũ | Tung đồng xu |
|---|---|---|---|
| Log-loss | **0,6175** | 0,6481 | 0,6931 |
| Độ chính xác | **63,1%** | 60,9% | 50% |
| Brier | **0,2152** | 0,2286 | 0,25 |

Trọng số lưu vào DB (fit trên toàn bộ 2.168 trận): `team=0.709`, `hero=1.023`, `matchup=3.0`,
bias phe Radiant `+0.152`.

**Hiệu chuẩn trên tập test** — cột "dự đoán" và "thực tế" bám nhau khá sát, nghĩa là con số %
mà app đưa ra có ý nghĩa thật chứ không chỉ là thứ tự hơn kém:

| Khoảng dự đoán | Số trận | App dự đoán | Thực tế |
|---|---|---|---|
| 0–20% | 7 | 16,6% | 0,0% |
| 20–40% | 79 | 32,5% | 25,3% |
| 40–60% | 245 | 50,4% | 46,5% |
| 60–80% | 181 | 68,1% | 69,1% |
| 80–100% | 30 | 83,4% | 90,0% |

**Trên trận pro nói chung, O/U vẫn là điểm yếu**: độ chính xác 54,1% trong khi tỉ lệ over thực tế
là 54,6% — mô hình gần như chỉ đang đoán theo xu hướng chung. Nhưng **riêng ở TI thì khác**: nhờ
`duration_shift` ở mục 4.3, độ chính xác O/U trên 59 ván TI là **72,9%** (tỉ lệ over thực tế 71,2%,
mô hình chưa hiệu chỉnh đạt 67,8%). Nói thẳng: phần lớn giá trị đến từ việc nhận ra ván TI dài hơn
mặt bằng, chứ chưa phải từ việc phân biệt ván nào dài ván nào ngắn.

**Còn thứ đã thử và không dùng** (ghi lại để khỏi thử lại):

- *Đánh trọng số theo thời gian* (trận mới tính nặng hơn, half-life 45–365 ngày): log-loss trên tập
  test đi ngang trong khoảng 0,6173–0,6185 so với 0,6175 khi không đánh trọng số — chênh lệch ở mức
  nhiễu, đổi dấu tuỳ half-life. Không đáng thêm một knob nữa. Không dùng.
- *Dò lại tham số Elo* (`ELO_K` 14–56 × half-life 120–∞ × cửa sổ 365–1000 ngày, 75 tổ hợp): toàn bộ
  lưới nằm trong khoảng log-loss 0,6606–0,6667, tức chênh nhau ở mức nhiễu. Cấu hình hiện tại
  (K=28, half-life 300, 640 ngày) đạt 0,6622 — đã đủ tốt, không đổi.
- *Nhân một hệ số nhiệt độ lên toàn bộ logit ở TI* (kiểu Platt scaling): fit trên ngày 1 cho hệ số
  1,5 nhưng chấm trên ngày 2 lại **tệ hơn** để nguyên. Không dùng — cái sai không nằm ở độ tự tin
  tổng thể mà nằm ở riêng số hạng hero.

### 4.5 Giới hạn cần biết

- **Hiệu chỉnh TI dựa trên 2 ngày vòng bảng.** Vòng playoff là BO3/BO5 loại trực tiếp, đấu pháp và
  nhịp độ có thể khác hẳn. Sau mỗi ngày thi đấu nên chạy lại `refresh drafts` rồi
  `evaluate --apply` để hiệu chỉnh cập nhật theo dữ liệu mới nhất.
- **`hero_mult = 0,50` là kết quả có shrink mạnh, không phải kết luận chắc chắn.** Ước lượng thô là
  0,00 (tức "bỏ hẳn số hạng hero ở TI"), bootstrap ủng hộ ở mức 89% — đủ để nghiêng cán cân, chưa đủ
  để chắc. Prior 60 ván cố tình giữ nó ở giữa cho tới khi có thêm dữ liệu.
- **Ảnh hưởng của hero lên thời lượng cần mẫu lớn.** Với vài trăm trận pro (~30 trận/hero), sai số
  chuẩn của mỗi hero còn lớn hơn cả tín hiệu, nên shrinkage sẽ ép nó gần bằng 0 — đúng về mặt thống
  kê, nhưng nghĩa là lúc đó hero gần như không đổi được dự đoán O/U. Chạy `refresh drafts` nhiều lần
  để mẫu lớn dần (dữ liệu tích luỹ, không tải lại).
- **Bảng khắc chế hero là từ trận public**, không phải trận pro — pro không đủ mẫu để có bảng
  hero-vs-hero đáng tin.
- **Số hạng tuyển thủ không được fit bằng backtest.** Chấm nó trên các trận quá khứ cần record của
  từng người *tại thời điểm đó*, mà DB chỉ lưu số liệu tổng hiện tại — dùng số hiện tại là nhìn
  trước kết quả. Vì vậy `W_PLAYER_HERO` là hằng số đặt tay trong `config.py` (0.35, trần 0.60
  log-odds), cố ý để khiêm tốn.
- **Winrate tuyển thủ gồm cả trận rank** — người hay đổi hero trong pub sẽ có mẫu khác với hero họ
  thật sự cầm khi thi đấu. Tín hiệu này nói về độ thuần thục hero, không phải phong độ thi đấu.
- **Mô hình không biết** ai đang bệnh, lỗi mạng, hay áp lực tâm lý TI. Roster đổi phút chót thì
  nguồn dữ liệu cũng trễ — dùng `python -m backend roster` để sửa tay (mục 5).
- **Tên tổ chức bị tái sử dụng trên OpenDota.** Nigma Galaxy có hai entity trùng tên: một đã ngừng
  đấu từ 8/5 nhưng còn rating 1403 từ thời hoàng kim, một đang thi đấu ở TI với rating 1278. Khi
  trùng tên, `matching.build_index` giờ ưu tiên **đội đấu gần đây nhất** chứ không phải rating cao
  nhất — rating là tiêu chí cũ và nó chọn nhầm đội chết, kéo theo sai cả Elo, lịch sử đối đầu lẫn
  đội hình của Nigma. Nếu thấy một đội có rating hoặc đội hình vô lý, kiểm tra `ti_teams.team_id`
  trước tiên.
- Đội mới / ít trận (ví dụ Iron Wing, HULIGANI) có rating kém tin cậy — app sẽ ghi chú điều này.

Đây là công cụ thống kê tham khảo, **không phải lời khuyên cá cược**.

## 5. Lệnh CLI

```bash
python -m backend status
```

```bash
python -m backend refresh core
```

```bash
python -m backend refresh history
```

```bash
python -m backend refresh drafts --drafts 600
```

| Phase | Số request | Nội dung |
|---|---|---|
| `core` | ~10 | giải đấu, 16 đội + đội hình, 127 hero, lịch thi đấu |
| `history` | ~16 | toàn bộ lịch sử trận pro của các đội TI → Elo |
| `players` | ~120 | đội hình từng đội + bảng winrate theo hero của mỗi tuyển thủ |
| `drafts` | 1 / trận | picks + thời lượng của các trận pro gần đây |
| `results` | ~15 | kho kết quả series theo ngày từ hawk.live |
| `matchups` | 127 | bảng khắc chế hero-vs-hero cho toàn bộ hero |

`drafts` chạy tăng dần: mỗi lần chạy chỉ tải các trận chưa có, nên gọi lại nhiều lần là an toàn.
`players` cũng vậy: bảng hero của một người chỉ tải lại sau `PLAYER_REFRESH_TTL` (mặc định 3 ngày),
và nếu bạn chọn một tuyển thủ chưa có dữ liệu thì lần dự đoán đó tự tải bổ sung.

```bash
python -m backend refresh players
```

**Sửa tay đội hình khi có thay đổi roster.** Cờ "đang trong đội" của OpenDota suy ra từ việc ai đã
thực sự ra sân, nên nó trễ vài ngày sau một lần đổi người — đúng những ngày quan trọng nhất khi giải
đang diễn ra. Ghi đè bằng:

```bash
python -m backend roster --team lgd-gaming --current Topson --former TaiLung
```

Các chỉnh tay này nằm trong bảng `roster_overrides` và được **áp lại sau mỗi lần `refresh players`**,
nên không bị ghi đè ngược. Xem danh sách đang có bằng `python -m backend roster`; bỏ chỉnh tay của
một đội bằng `--clear` rồi chạy `refresh players`.

Dọn cache HTTP cũ và thu nhỏ file database:

```bash
python -m backend compact
```

Backtest mô hình, fit lại trọng số và hiệu chỉnh theo giải (`--apply` để lưu và dùng luôn):

```bash
python -m backend evaluate --apply
```

**Quy trình nên chạy sau mỗi ngày thi đấu TI** — kết quả trong ngày vào Elo, draft trong ngày vào
hiệu chỉnh theo giải:

```bash
python -m backend refresh history
```

```bash
python -m backend refresh drafts --drafts 200
```

```bash
python -m backend evaluate --apply --since 2026-08-13
```

Trong output của `evaluate`, hai khối đáng đọc nhất là `ti_context` (hiệu chỉnh đang được lưu) và
`ti_context_holdout` (fit trên nửa đầu số ván TI, chấm trên nửa sau — chỗ để tự kiểm chứng).

## 6. API

| Endpoint | Mô tả |
|---|---|
| `GET /api/status` | thông tin giải + tình trạng dữ liệu local + `weights` và `ti_context` đang dùng |
| `GET /api/teams` | 16 đội TI kèm rating, đội hình, danh sách tuyển thủ chọn được (`roster`) |
| `GET /api/heroes` | 127 hero kèm winrate ước tính |
| `GET /api/roster/{slug}` | tuyển thủ của một đội; thêm `?hero_id=` để kèm record của họ trên hero đó |
| `GET /api/players/{account_id}/heroes` | các hero một tuyển thủ chơi nhiều nhất |
| `GET /api/schedule` | lịch thi đấu từ GosuGamers |
| `GET /api/results` | `?scope=ti\|all\|teams` — lịch sử kết quả; `scope=teams` cần thêm `team_a`, `team_b` |
| `POST /api/predict` | `{team_a, team_b, heroes_a[], heroes_b[], players_a[], players_b[], line_minutes}` |
| `POST /api/refresh` | `{phase: core\|history\|players\|drafts\|results\|all, draft_limit}` |
| `GET /api/refresh/status` | tiến độ job đang chạy |

`players_a[]` / `players_b[]` là account id OpenDota, xếp **cùng thứ tự** với `heroes_a[]` /
`heroes_b[]` — phần tử thứ i là người cầm hero thứ i; để `null` nếu không muốn tính.

Response của `/api/predict` có thêm `factors.ti_context` (hiệu chỉnh theo giải đang áp) và
`factors.duration_terms.ti_context_log` (phần Δ_TI cộng vào thời lượng).

Ví dụ:

```bash
curl -X POST http://127.0.0.1:8000/api/predict -H "Content-Type: application/json" -d "{\"team_a\":\"team-spirit\",\"team_b\":\"team-falcons\",\"heroes_a\":[10,13],\"heroes_b\":[1,17],\"players_a\":[321580662,106305042],\"players_b\":[null,null],\"line_minutes\":41}"
```

## 7. Cấu trúc

```
backend/
  config.py            tham số & endpoint
  db.py                schema SQLite
  fetcher.py           HTTP có rate-limit + cache
  matching.py          khớp tên đội giữa các nguồn
  sources/             liquipedia.py · gosugamers.py · hawk.py · opendota.py
  ingest.py            thu thập theo từng phase
  model.py             Elo, draft, tuyển thủ-hero, mô hình thời lượng
  app.py               FastAPI
  __main__.py          CLI
frontend/
  index.html  styles.css  app.js
tools/
  create_shortcut.ps1  tạo shortcut Desktop / Start Menu
  make_icon.py         sinh assets/ti2026.ico
  open_when_ready.py   đợi server bind cổng rồi mới mở browser
assets/
  ti2026.ico           icon của shortcut
data/
  dota_ti.sqlite       toàn bộ dữ liệu local
```

## 8. Gặp sự cố

| Triệu chứng | Nguyên nhân & cách xử lý |
|---|---|
| Mở `127.0.0.1:8000` báo không kết nối được | Server chưa chạy. Double-click shortcut và **giữ cửa sổ đen mở**. |
| Giao diện cũ, sửa CSS không thấy đổi | Nhấn **Ctrl+F5** một lần để bỏ cache cũ của trình duyệt. |
| `run.bat` báo không tìm thấy Python | Cài Python 3.10+ và tick "Add python.exe to PATH" khi cài. |
| Cổng 8000 đã bị chiếm | Chạy `python -m backend serve --port 8090` rồi mở `127.0.0.1:8090`. |
| File database phình to | `python -m backend compact` |

Muốn chỉnh mô hình thì sửa các hằng số ở đầu `backend/config.py` (`W_HERO_WINRATE`, `W_MATCHUP`,
`ELO_K`, `DURATION_WINDOWS`, `OVER_UNDER_LINE_MIN`, …). Riêng phần hiệu chỉnh theo giải có nhóm
knob riêng: `TI_CONTEXT_MIN_GAMES`, `TI_DRAFT_PRIOR_GAMES`, `TI_DURATION_PRIOR_GAMES` — tăng prior
lên là hiệu chỉnh thận trọng hơn, hạ xuống là tin dữ liệu TI nhiều hơn.
