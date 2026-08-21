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
5. Chọn **thể thức**: `BO1` cho một ván lẻ, `BO3` / `BO5` cho một loạt đấu. Toàn bộ nhánh Main Event
   là Bo3 và chung kết là Bo5, nên từ 20/8 trở đi gần như lúc nào cũng nên để BO3. Chọn BO3/BO5 sẽ
   hiện thêm ô **tỉ số hiện tại** — nhập 1–0 nếu loạt đang đá dở, app sẽ tính lại cả xác suất ván
   sắp tới lẫn xác suất cả loạt.
6. Bấm **DỰ ĐOÁN**.
7. Bấm vào một trận trong "Lịch thi đấu TI 2026" để nạp nhanh 2 đội của trận đó.

Với BO3/BO5, kết quả có thêm thẻ **Kết quả loạt đấu**: xác suất thắng chuỗi của mỗi đội, phân bố
tỉ số (2–0 / 2–1 / …), số ván còn lại dự kiến và tổng thời lượng dự kiến của cả loạt. Thẻ *Dự đoán
thắng thua* phía trên vẫn là xác suất của **ván sắp tới**, không phải của cả loạt.

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
| [Liquipedia — Main Event](https://liquipedia.net/dota2/The_International/2026/Main_Event) | Nhánh Main Event: 8 đội, cặp đấu và lịch từng vòng | như trên, parse template `Bracket` |
| [GosuGamers](https://www.gosugamers.net/dota2) | Kết quả và trận đang live của TI 2026 | Scrape HTML |
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
             +  W_series · (số ván A đã thắng trong chuỗi − số ván B đã thắng)
```

`m_hero` / `m_matchup` là **hiệu chỉnh theo giải**, fit từ 109 ván vòng bảng TI 2026. Cả hai **đang
bằng 1** vì không qua được kiểm chứng out-of-sample — công thức hiện chạy đúng dạng cũ. Mục 4.3 kể
lại đầy đủ chuyện này.

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

5. **Thế dẫn trong chuỗi** — chỉ có tác dụng khi ván đang hỏi là ván thứ hai trở đi của một Bo3/Bo5.
   Đội đang dẫn thắng ván tiếp theo nhiều hơn mức rating của nó nói. Xem mục 4.5.

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
- **Δ_TI** là phần dư còn lại sau tất cả những thứ trên, đo trên chính các ván TI đã đấu. Hiện
  **bằng 0**: nó không qua được kiểm chứng, xem mục 4.3.

### 4.3 Hiệu chỉnh theo giải — và vì sao nó đang tắt

Ý tưởng: một ván TI có thể không giống một ván pro trung bình (hai bên đều là đội đỉnh, bốc hero từ
cùng một pool đã chuẩn bị), nên app fit vài hiệu chỉnh riêng cho TI từ chính các ván đã đấu:
`hero_mult`, `matchup_mult` nhân vào hai số hạng draft, và `duration_shift` cộng vào thời lượng.

**Sau 3 ngày TI 2026, không hiệu chỉnh nào trụ được.** Đây là bài học đáng giá hơn cả bản thân cơ
chế, nên ghi lại đầy đủ.

Sau ngày 1–2 (59 ván), mọi dấu hiệu đều chỉ về một hướng: bỏ số hạng winrate hero ra khỏi mô hình
làm log-loss trên TI tốt lên 0,6583 → 0,6409, trong khi ở giải khác thì ngược lại; bootstrap 3.000
lần ủng hộ 89%; kiểm chứng fit-ngày-1-chấm-ngày-2 tốt lên cả 4 chỉ số. Giá trị fit là
`hero_mult = 0,50`. Nghe rất thuyết phục.

Ngày 3 (38 ván) đảo ngược hoàn toàn:

| | ngày 1–2 (n=59) | ngày 3 (n=38) | cả 3 ngày (n=97) |
|---|---|---|---|
| log-loss, **có** số hạng hero | 0,6619 | **0,6221** | 0,6463 |
| log-loss, **bỏ** số hạng hero | **0,6409** | 0,6532 | 0,6457 |
| bootstrap ủng hộ "bỏ hero" | 89,0% | **2,7%** | 51,9% |
| phần dư thời lượng | +0,0625 | **−0,0258** | +0,0279 (se 0,0274) |
| tỉ lệ over 41′ | 71,2% | 55,3% | 64,9% |

Trên 97 ván, "có hero" và "bỏ hero" chênh nhau 0,0006 log-loss và bootstrap về đúng 52% — tức là
đồng xu. Phần dư thời lượng còn +0,028 với se 0,027, tức t ≈ 1,0.

Tệ hơn: hiệu chỉnh fit từ ngày 1–2 đã **được áp dụng thật** và chấm trên ngày 3 — dữ liệu nó chưa hề
thấy — thì **làm mọi thứ xấu đi**:

| Chỉ số trên ngày 3 | Không hiệu chỉnh | Có hiệu chỉnh (fit từ ngày 1–2) |
|---|---|---|
| Log-loss | **0,6221** | 0,6359 |
| Độ chính xác | **68,4%** | 65,8% |
| Brier O/U | **0,2468** | 0,2554 |

### Sửa cơ chế, không chỉ sửa con số

Cái sai không nằm ở giá trị 0,50 mà ở **quy trình**: phiên bản đầu fit ra gì thì áp dụng nấy.
Shrinkage giữ con số ở mức khiêm tốn nhưng nó *không phân biệt được tín hiệu thật với may mắn* — nó
chỉ hỏi "mẫu có lớn không", không hỏi "hiệu ứng có lặp lại không".

Nên giờ hiệu chỉnh phải **tự chứng minh trên dữ liệu nó chưa thấy** mới được dùng: fit trên nửa cũ
của các ván TI, chấm trên nửa mới, chỉ giữ phần nào thắng được "không làm gì". Hai nhóm được gác
riêng vì chúng trả lời hai câu hỏi khác nhau — nhóm draft theo log-loss thắng/thua, `duration_shift`
theo Brier O/U.

Kết quả hiện tại (fit trên 48 ván cũ, chấm trên 49 ván mới):

| | Không hiệu chỉnh | Có hiệu chỉnh | Kết luận |
|---|---|---|---|
| Log-loss | **0,6436** | 0,6510 | ✗ loại nhóm draft |
| Brier O/U | **0,2440** | 0,2536 | ✗ loại `duration_shift` |

Cả hai bị loại → `hero_mult = matchup_mult = 1,0`, `duration_shift = 0` → **mô hình chạy đúng như
khi không có bất kỳ điều chỉnh TI nào**. `/api/status` và `factors.ti_context` báo `active: false`.

Cơ chế vẫn nằm đó và tự bật lại nếu về sau hiệu ứng trở thành thật — vòng playoff BO3/BO5 hoàn toàn
có thể khác vòng bảng. Ngưỡng để chạm vào bất cứ thứ gì là `TI_CONTEXT_MIN_GAMES × 2` ván (mặc định
40): cần một nửa để fit và một nửa để chấm, còn "chưa đủ để kiểm tra" thì đồng nghĩa "chưa được áp
dụng".

**Điều rút ra:** với cỡ mẫu vài chục ván, một hiệu ứng "5 sigma trên giấy" vẫn có thể là nhiễu.
Shrinkage là chưa đủ; thứ duy nhất đáng tin là kiểm chứng trên dữ liệu chưa thấy.

### Nhãn stage: vòng bảng và nhánh Main Event

TI 2026 chạy Thuỵ Sĩ 16 đội (Round 1–5) rồi các series **Elimination Round** chốt 8 suất vào Main
Event — tất cả vẫn là **vòng bảng**, 109 ván trong 4 ngày 13–16/8. Nhánh Main Event giữa 8 đội là
phần đá sau.

Chỗ này dễ đọc nhầm và tôi đã đọc nhầm một lượt: GosuGamers gắn `Main Event - Elimination Round`,
nghe như đã sang nhánh, nên 12 ván ngày 4 từng bị gắn nhãn `playoff`. hawk.live mới là nguồn đúng —
nó xếp cả 109 ván dưới một tournament `The International 2026 Group Stage`. Bài học nằm trong
`KNOCKOUT_WORDS`: `"main event"` không phải từ khoá nhánh (GosuGamers dùng nó cho cả kỳ LAN), và
`"elimination"` cũng không (đó là vòng loại *trong* giai đoạn Thuỵ Sĩ).

Khi nhánh Main Event bắt đầu, `ingest.label_match_stages` sẽ bắt nó qua các từ upper/lower bracket,
quarterfinal, semifinal, grand final — và các ván đó thành holdout tiến về phía trước thật sự. Nhãn
vòng lấy từ trang bracket của Liquipedia, nạp sẵn vào lịch ngay khi cặp đấu được xác định.

### Ước lượng thô hội tụ về "không có gì"

Đây là bằng chứng gọn nhất cho thấy hiệu ứng ban đầu chỉ là nhiễu — theo dõi cùng một con số khi
vòng bảng đầy dần:

| Dữ liệu | `hero_mult` thô | `duration_shift` thô | se | t |
|---|---|---|---|---|
| ngày 1–2 (59 ván) | 0,00 | +0,068 | 0,036 | 1,9 |
| ngày 1–3 (97 ván) | 0,35 | +0,028 | 0,027 | 1,0 |
| **ngày 1–4 (109 ván)** | **0,75** | **+0,017** | 0,026 | **0,7** |

`hero_mult` bò từ 0,00 về 0,75 (1,0 = không hiệu chỉnh) và t của thời lượng rơi từ 1,9 xuống 0,7.
Đúng cái mà một hiệu ứng không tồn tại phải làm khi mẫu lớn dần.

Cổng kiểm chứng trên 109 ván (fit 54 ván cũ, chấm 55 ván mới) vẫn loại cả hai: log-loss 0,6375 →
0,6483, Brier O/U 0,2604 → 0,2760.

Và kiểm chứng theo thời gian — fit trên 97 ván ngày 1–3, chấm trên 12 ván ngày 4 chưa từng thấy:

| Chấm 12 ván ngày 4 bằng | Log-loss | Độ chính xác | Brier O/U |
|---|---|---|---|
| Mô hình trơn (hiệu chỉnh đã bị loại) | **0,6538** | **66,7%** | 0,2998 |
| Hiệu chỉnh thô ngày 1–3, không shrink không gác cổng | 0,7149 | 50,0% | 0,3181 |

Dòng dưới là đúng thứ phiên bản đầu của `fit_ti_context` sẽ đưa vào chạy: nó biến 66,7% thành tung
đồng xu.

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

Dataset 2.779 trận (15/5 → 20/8/2026, đã gồm 10 ván Main Event ngày 1), fit trên 2.084 trận cũ,
chấm trên 695 trận mới hơn:

| Chỉ số | Trọng số đã fit | Trọng số config cũ | Tung đồng xu |
|---|---|---|---|
| Log-loss | **0,6108** | 0,6481 | 0,6931 |
| Độ chính xác | **66,0%** | 61,6% | 50% |
| Brier | **0,2118** | 0,2285 | 0,25 |

Trọng số lưu vào DB (fit trên toàn bộ 2.779 trận, gồm cả 119 ván TI): `team=0.719`, `hero=0.971`,
`matchup=3.0`, bias phe Radiant `+0.130`. Hệ số chuỗi `series=0.192` (mục 4.5).

`matchup=3.0` đang **chạm trần cứng** trong `fit_weights`. Nghĩa là hàm likelihood còn muốn đẩy nó
cao hơn nữa, và trần đó — chứ không phải dữ liệu — mới là thứ quyết định con số. Không sửa vội: số
hạng khắc chế đã được chuẩn hoá về "mỗi hero" nên trọng số lớn không tự nó vô lý, nhưng nó là một
điểm cần để mắt chứ không phải một kết quả fit sạch.

**Hiệu chuẩn trên tập test** — cột "dự đoán" và "thực tế" bám nhau khá sát, nghĩa là con số %
mà app đưa ra có ý nghĩa thật chứ không chỉ là thứ tự hơn kém:

| Khoảng dự đoán | Số trận | App dự đoán | Thực tế |
|---|---|---|---|
| 0–20% | 8 | 16,1% | 0,0% |
| 20–40% | 122 | 32,4% | 20,5% |
| 40–60% | 300 | 50,2% | 47,0% |
| 60–80% | 231 | 68,4% | 68,4% |
| 80–100% | 34 | 83,2% | 88,2% |

**O/U vẫn là điểm yếu nhất.** Trên tập test độ chính xác 54,5% trong khi tỉ lệ over thực tế là
53,9% — mô hình gần như chỉ đang đoán theo xu hướng chung. Riêng 12 ván cuối vòng bảng (ngày 4) chỉ
đúng 25%, vì chúng ngắn bất thường (33,3% vượt mốc 41′) trong khi mô hình vẫn nghiêng OVER theo mặt
bằng ba ngày trước. Hướng sửa từng có vẻ hứa hẹn (`duration_shift`) đã bị chính kiểm chứng của nó
loại — xem mục 4.3. Phần thắng/thua đáng tin hơn hẳn phần thời lượng.

**Còn thứ đã thử và không dùng** (ghi lại để khỏi thử lại):

- *Đánh trọng số theo thời gian* (trận mới tính nặng hơn, half-life 45–365 ngày): log-loss trên tập
  test đi ngang, chênh lệch ở mức nhiễu và đổi dấu tuỳ half-life. Không đáng thêm một knob nữa.
- *Hiệu chỉnh riêng cho TI* (`hero_mult`, `duration_shift`): fit được, nhưng không qua kiểm chứng
  out-of-sample. Cơ chế vẫn còn và tự bật lại nếu hiệu ứng thành thật — mục 4.3.
- *Dò lại tham số Elo* (`ELO_K` 14–56 × half-life 120–∞ × cửa sổ 365–1000 ngày, 75 tổ hợp): toàn bộ
  lưới nằm trong khoảng log-loss 0,6606–0,6667, tức chênh nhau ở mức nhiễu. Cấu hình hiện tại
  (K=28, half-life 300, 640 ngày) đạt 0,6622 — đã đủ tốt, không đổi.
- *Nhân một hệ số nhiệt độ lên toàn bộ logit ở TI* (kiểu Platt scaling): fit trên ngày 1 cho hệ số
  1,5 nhưng chấm trên ngày 2 lại **tệ hơn** để nguyên. Không dùng — cái sai không nằm ở độ tự tin
  tổng thể mà nằm ở riêng số hạng hero. Thử lại sau Main Event ngày 1 trên cả 119 ván TI: hệ số tốt
  nhất là 1,0–1,2 trên cả pro nói chung lẫn vòng bảng TI, tức mô hình vốn đã hiệu chuẩn đúng và
  không có gì để scale.
- *Thêm một Elo "phong độ gần đây" bên cạnh Elo dài hạn* (half-life 30/45/120 ngày, K 28–40, đưa
  vào thành số hạng thứ tư): log-loss tập test 0,6107 → 0,6099. Chênh lệch ở mức nhiễu, và trọng số
  Elo dài hạn bị chia đôi để nhường chỗ. Elo hiện tại đã tự hạ K theo tuổi trận nên nó đang làm
  đúng việc này rồi; không thêm knob.

### 4.5 Loạt đấu Bo3/Bo5 — câu hỏi mà Main Event thật sự hỏi

Vòng bảng đá Bo2, nhưng **toàn bộ nhánh Main Event là Bo3, chung kết là Bo5**. Từ ngày 20/8 trở đi,
"đội nào thắng ván này" chỉ là nửa câu trả lời — cái người xem cần là "đội nào qua được vòng này".
Hai câu hỏi cho hai con số khác nhau: một đội hơn 55% ở một ván là 57,5% ở một Bo3, và 59,3% ở Bo5.

App có nút chọn **BO1 / BO3 / BO5** ngay dưới nút Dự đoán, kèm ô nhập **tỉ số hiện tại** cho loạt
đang đá dở. Kết quả trả về thêm một thẻ *Kết quả loạt đấu*: xác suất thắng chuỗi, **phân bố tỉ số**
(2–0 / 2–1 / 1–2 / 0–2), số ván dự kiến và tổng thời lượng dự kiến của cả loạt.

**Các ván trong một chuỗi không độc lập nhau.** Dựng lại chuỗi từ log trận (cùng cặp đội, cùng giải,
hai ván cách nhau dưới `SERIES_MAX_GAP` = 3 giờ) rồi đo trên **3.259 ván** đá ở thế tỉ số lệch:

| | Kỳ vọng theo Elo | Thực tế |
|---|---|---|
| Đội thắng ván 1 thắng luôn ván 2 | 56,4% | **60,1%** (n = 2.373) |
| Đội đang dẫn 1–0 thắng ván sau | 55,8% | **61,1%** (n = 1.197) |
| Đội đang bị dẫn 0–1 thắng ván sau | 43,1% | **40,7%** (n = 1.225) |

Elo tự nó đã ăn được khoảng một nửa hiệu ứng — nó cập nhật sau **từng ván**, nên thắng một ván đã
đẩy rating lên ~0,14 log-odds trước ván sau. Phần **còn dư** sau khi trừ hết đi là số hạng mới:

```
W_series = +0.192 log-odds mỗi ván dẫn trước
```

Fit bằng max-likelihood trên 1.054 ván có draft ở thế tỉ số lệch, shrink về 0 với
`SERIES_MOMENTUM_PRIOR = 400` ván giả định (thô 0,265 → dùng 0,192), rồi **phải qua kiểm chứng
out-of-sample** đúng như trọng số chính: fit trên phần cũ, chấm trên 317 ván mới hơn — log-loss
0,6064 → **0,5994**, qua. Nếu một lần chạy sau nó trượt, hệ số tự về 0 và các ván lại được coi là
độc lập.

**Một điểm phải nói thẳng:** trên chính dữ liệu TI 2026 (48 ván) hiệu ứng này **không** cải thiện gì
— log-loss 0,614 → 0,6185. Số hạng vẫn được dùng, vì 48 ván không đủ để lật 3.259 ván, nhưng
`evaluate` in riêng lát cắt TI ra (`series_momentum.ti_slice`) để chuyện đó không bị giấu đi. Đây
khác hẳn với `hero_mult` ở mục 4.3: cái đó là hiệu chỉnh *của riêng TI*, chỉ có dữ liệu TI để dựa
vào, nên dữ liệu TI có quyền phủ quyết nó.

**Đo ở cấp chuỗi, không phải cấp ván.** `evaluate` chấm luôn dự đoán chuỗi *đưa ra trước ván đầu
tiên* — thông tin duy nhất mà một dự đoán nhánh từng có:

| Lát cắt | Số chuỗi | Log-loss | Độ chính xác |
|---|---|---|---|
| Tập test (pro nói chung) | 256 | 0,6372 | 65,6% |
| Vòng bảng TI 2026 | 44 | 0,6635 | 56,8% |
| **Main Event ngày 1** | **4** | **0,4617** | **75%** |

Ngày 1 nhánh: đúng Spirit thắng Iron Wing (dự đoán chuỗi 75,1%), đúng VISION thắng BoomBoys (64,3%),
đúng Yandex thắng Liquid (87,8% cho Yandex), **sai Falcons thua Nigma** (mô hình cho Falcons 62,8%).
Bốn chuỗi là một giai thoại chứ không phải một phép đo — nhưng đáng chú ý là ở **cấp ván** cùng ngày
đó mô hình chỉ đúng 6/10 với log-loss 0,7115, tệ hơn tung đồng xu. Gộp ván lại thành chuỗi lọc bớt
nhiễu, và đó chính là lý do thẻ chuỗi tồn tại.

### 4.6 Giới hạn cần biết

- **Hiệu chỉnh riêng cho TI hiện đang tắt** vì không qua kiểm chứng (mục 4.3). Sau mỗi ngày thi đấu
  nên chạy lại `refresh core` + `refresh history` + `refresh drafts` rồi `evaluate --apply`: nếu
  hiệu ứng trở thành thật, cổng kiểm chứng sẽ tự bật nó lên.
- **Hiệu chỉnh fit trên vòng bảng nhưng lúc dự đoán sẽ áp cho cả nhánh Main Event.** Nhánh loại
  trực tiếp giữa 8 đội mạnh nhất không nhất thiết giống vòng bảng 16 đội, nên nếu về sau cổng kiểm
  chứng bật hiệu chỉnh lên thì đây là chỗ cần xem lại. Hiện chưa có ván nhánh nào để fit riêng.
- **Đừng tin một hiệu ứng chỉ mới thấy trên vài chục ván.** Sau ngày 1–2, `hero_mult` fit ra 0,50
  với bootstrap 89% ủng hộ; ngày 3 đảo ngược và bootstrap về 2,7%. Mọi con số trong mục 4.3 nên đọc
  kèm câu này.
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

Trong output của `evaluate`, khối đáng đọc nhất là `ti_context`:

- `raw` — hiệu chỉnh **fit ra được** từ các ván TI đã đấu.
- `validation` — kết quả kiểm chứng trên nửa số ván TI mới nhất, kèm `kept: true/false` cho từng
  nhóm.
- các trường ở cấp ngoài cùng (`hero_mult`, `matchup_mult`, `duration_shift`) — hiệu chỉnh **thực sự
  được áp dụng**, tức là phần đã qua kiểm chứng. Chúng bằng 1/1/0 nghĩa là mô hình đang chạy không
  có điều chỉnh TI nào.

Đừng đọc `raw` mà tưởng đó là thứ đang chạy — chênh lệch giữa `raw` và cấp ngoài cùng chính là phần
bị cổng kiểm chứng loại.

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
| `POST /api/predict` | `{team_a, team_b, heroes_a[], heroes_b[], players_a[], players_b[], line_minutes, best_of, series_a, series_b}` |
| `POST /api/refresh` | `{phase: core\|history\|players\|drafts\|results\|all, draft_limit}` |
| `GET /api/refresh/status` | tiến độ job đang chạy |

`players_a[]` / `players_b[]` là account id OpenDota, xếp **cùng thứ tự** với `heroes_a[]` /
`heroes_b[]` — phần tử thứ i là người cầm hero thứ i; để `null` nếu không muốn tính.

Response của `/api/predict` có thêm `factors.ti_context` (hiệu chỉnh theo giải đang áp) và
`factors.duration_terms.ti_context_log` (phần Δ_TI cộng vào thời lượng).

`best_of` nhận 1, 3 hoặc 5 (mặc định 1 — một ván lẻ, đúng như trước). Với `best_of > 1`, response có
thêm khối `series`: `p_series`, `scorelines[]`, `expected_maps`, `p_over_maps` và
`expected_total_minutes`. `series_a` / `series_b` là số ván **đã thắng** của loạt đang đá dở; nhập
một tỉ số đã kết thúc loạt (2 trong Bo3) sẽ bị từ chối với lỗi 400. Lúc đó `win_probability` vẫn là
xác suất của **ván sắp tới** — đã cộng thế dẫn — còn `series.p_map_level` là xác suất một ván khi tỉ
số đang hoà, tức đầu vào của phép tính chuỗi.

Ví dụ:

```bash
curl -X POST http://127.0.0.1:8000/api/predict -H "Content-Type: application/json" -d "{\"team_a\":\"team-spirit\",\"team_b\":\"team-falcons\",\"heroes_a\":[10,13],\"heroes_b\":[1,17],\"players_a\":[321580662,106305042],\"players_b\":[null,null],\"line_minutes\":41}"
```

Một Bo3 đang dẫn 1–0:

```bash
curl -X POST http://127.0.0.1:8000/api/predict -H "Content-Type: application/json" -d "{\"team_a\":\"team-spirit\",\"team_b\":\"team-vision\",\"best_of\":3,\"series_a\":1,\"series_b\":0}"
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
  model.py             Elo, draft, tuyển thủ-hero, mô hình thời lượng, phép tính Bo3/Bo5
  evaluate.py          backtest, fit trọng số, hiệu chỉnh giải, hệ số chuỗi
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
| Lịch sử kết quả thiếu ngày hôm nay / hôm qua | Bấm **Cập nhật dữ liệu** (nút này chạy cả phase `results`). Trang theo ngày của hawk.live chỉ được cache lâu khi ngày đó đã qua từ 2 hôm trở lên, nên hôm nay và hôm qua luôn được tải lại. |

Muốn chỉnh mô hình thì sửa các hằng số ở đầu `backend/config.py` (`W_HERO_WINRATE`, `W_MATCHUP`,
`ELO_K`, `DURATION_WINDOWS`, `OVER_UNDER_LINE_MIN`, …). Riêng phần hiệu chỉnh theo giải có nhóm
knob riêng: `TI_CONTEXT_MIN_GAMES`, `TI_DRAFT_PRIOR_GAMES`, `TI_DURATION_PRIOR_GAMES` — tăng prior
lên là hiệu chỉnh thận trọng hơn, hạ xuống là tin dữ liệu TI nhiều hơn.
