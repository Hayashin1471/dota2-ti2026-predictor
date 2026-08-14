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
logit(P_A) = W_team · (R_A − R_B)·ln10/400  +  W_hero · Σ Δlogit(winrate)  +  W_matchup · Δ khắc chế
             +  W_player · Σ Δlogit(winrate của tuyển thủ trên hero được gán)
```

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
P(over) = 1 − Φ( (ln(41·60) − μ) / σ )
```

- **μ_nền** lấy theo cửa sổ hẹp nhất còn đủ mẫu (mặc định 120 ngày). Điều này quan trọng: trung bình
  toàn bộ lịch sử trong DB là ~37 phút, nhưng pro Dota gần đây là **~41 phút** — đúng ngay mốc 41,
  nên mốc này thực sự cân bằng chứ không lệch hẳn về một phía.
- **Nhịp độ đội** đo trong cùng cửa sổ với mặt bằng chung, nên độ trôi theo patch không bị đếm hai lần.
- **Ảnh hưởng đội hình** cộng độ lệch log-thời-lượng của 10 hero được chọn, mỗi hero bị shrink theo
  `n/(n + DURATION_PRIOR_GAMES)`.

### 4.3 Fit trọng số & backtest

`python -m backend evaluate` chấm điểm mô hình trên chính dữ liệu đã tải:

- **Dataset**: mọi trận pro trong DB có đủ 10 pick.
- **Đặc trưng chống rò rỉ**: cột `matches.pre_elo_*` lưu Elo của 2 bên **trước** trận
  (ghi lại trong lúc chạy Elo), nên mô hình không nhìn thấy kết quả khi chấm chính nó.
- **Fit**: gradient ascent trên log-likelihood có phạt L2, cho 3 trọng số + 1 hệ số bias.
  Bias hấp thụ lợi thế phe Radiant — app không dùng nó (người dùng chọn đội chứ không chọn phe),
  nhưng bỏ nó ra thì lợi thế đó sẽ bị dồn nhầm vào 3 trọng số kia.
- **Chia dữ liệu theo thời gian**: fit trên 75% trận cũ, chấm trên 25% trận mới hơn.
- `--apply` lưu trọng số vào DB; `model.weights()` sẽ ưu tiên dùng chúng thay cho hằng số config.

**Không thể "train" bằng một ngày thi đấu.** 18 trận không đủ để xác định 3 tham số — ép nó fit
thì chỉ là fit nhiễu. Các trận trong ngày được **chấm như mẫu held-out**, không đưa vào fit.

**Vì sao số hạng hero dùng `pub_winrate` chứ không phải `winrate`:** `winrate` được kéo về phía
mẫu trận pro mà app tự tải — tức là **chính tập trận đang fit**. Dùng nó thì đặc trưng hero mang sẵn
kết quả nó phải dự đoán. Đo thử: mẫu pro trung vị 106 ván/hero, lệch trung bình 2 điểm % so với
`pub_winrate`, và số hạng hero khi đó đóng góp 0.487 logits — **lớn hơn cả sức mạnh đội (0.355)**,
điều vô lý với Dota chuyên nghiệp. Chuyển sang `pub_winrate` (chỉ từ trận public, độc lập hoàn toàn
với tập trận pro): đóng góp về 0.276 logits và log-loss trên test **tốt lên** (0.6291 → 0.6254).

Vẫn còn một điểm chưa xử lý được: bảng tỉ lệ thắng và bảng khắc chế là số liệu **của patch hiện tại**
áp lên các trận trong quá khứ. Đây không phải rò rỉ kết quả, nhưng vẫn là một dạng "nhìn trước" nhẹ.

### Kết quả đo thực tế

Fit trên 1.377 trận (30/5 → 13/8/2026), chấm trên 459 trận mới hơn:

| Chỉ số | Trọng số đã fit | Trọng số config cũ | Tung đồng xu |
|---|---|---|---|
| Log-loss | **0.6254** | 0.6651 | 0.6931 |
| Độ chính xác | **63.8%** | 59.0% | 50% |
| Brier | **0.2186** | 0.2330 | 0.25 |

Trọng số fit được: `team=0.756`, `hero=1.048`, `matchup=3.0`, bias phe Radiant `+0.122`.

**Hiệu chuẩn trên tập test** — cột "dự đoán" và "thực tế" bám nhau khá sát, nghĩa là con số %
mà app đưa ra có ý nghĩa thật chứ không chỉ là thứ tự hơn kém:

| Khoảng dự đoán | Số trận | App dự đoán | Thực tế |
|---|---|---|---|
| 0–20% | 7 | 16.5% | 14.3% |
| 20–40% | 80 | 32.4% | 25.0% |
| 40–60% | 202 | 49.9% | 52.0% |
| 60–80% | 144 | 67.8% | 67.4% |
| 80–100% | 26 | 83.2% | 88.5% |

**Điểm yếu thật sự nằm ở O/U**: trên tập test, độ chính xác O/U chỉ **56.2%** trong khi tỉ lệ over
thực tế là 55.6% — nghĩa là mô hình gần như chỉ đang đoán theo xu hướng chung chứ chưa thêm được
mấy giá trị. Phần thắng/thua đáng tin hơn hẳn phần thời lượng.

### 4.4 Giới hạn cần biết

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
- **Mô hình không biết** ai đang bệnh, roster thay đổi phút chót, lỗi mạng, hay áp lực tâm lý TI.
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

Dọn cache HTTP cũ và thu nhỏ file database:

```bash
python -m backend compact
```

Backtest mô hình và fit lại trọng số (`--apply` để lưu và dùng luôn):

```bash
python -m backend evaluate --apply
```

## 6. API

| Endpoint | Mô tả |
|---|---|
| `GET /api/status` | thông tin giải + tình trạng dữ liệu local |
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
`ELO_K`, `DURATION_WINDOWS`, `OVER_UNDER_LINE_MIN`, …).
