# TODO — интеграция udp_lab_sim ↔ odmr

Зафиксированные выводы и план работ. Проект-приёмник: `odmr` (Linux, `packet_collector/fpga2.c`).

---

## Схема взаимодействия

```
┌─────────────────────────────┐         UDP/Ethernet          ┌─────────────────────────────┐
│  Windows (хост)             │  ──────────────────────────►  │  Ubuntu VM (VirtualBox)     │
│  udp_lab_sim                │      порт 4660, кадр 1066     │  odmr (cv_odmr / packet_    │
│  python udp_spammer.py      │                               │  collector)                 │
└─────────────────────────────┘                               │  → ch0_0.txt, analyze.py    │
                                                              └─────────────────────────────┘
```

- **Windows** — отправитель (`udp_lab_sim`)
- **Linux VM** — приёмник (`odmr`)
- Сеть VM: **Bridged Adapter**, чтобы пакеты ходили хост ↔ VM как между двумя машинами в LAN
- **Не loopback** — `odmr` принимает только кадры **1066 байт** через raw Ethernet

---

## Фаза 0 — Инфраструктура (Linux VM)

- [x] Установить **VirtualBox** на Windows
- [x] Ubuntu VM (Desktop, bridged `enp0s3`)
- [x] Сеть: **Bridged Adapter**
- [x] Зависимости: `build-essential`, `cmake`, `python3.14-dev`, `libplplot-dev`
- [x] Проект `odmr` в `~/odmr`, сборка `cmake .. && make` (без копирования `build/` с Windows)
- [x] IP VM: `192.168.1.9`; Windows хост: ~`192.168.1.4`
- [x] Связность: ping хост → VM OK

### Чеклист запуска VM

1. Запустить VM, войти в систему
2. `cd odmr/build && ./cv_odmr eth0` (или `enp0s3` — смотреть `ip link`)
3. На Windows:
   ```powershell
   python udp_spammer.py --dst-host <IP_VM> --count 100
   ```
4. В VM должны появиться файлы `ch0_0.txt` / `ch2_0.txt` (после доработок Фазы 1)

### WSL2

- [ ] **Не использовать WSL2** для `odmr` — raw capture (`AF_PACKET`) там ненадёжен; нужна полноценная VM

---

## Фаза 1 — Совместимость udp_lab_sim с odmr (код)

### P0 — обязательно

- [x] Новый `body_mode` **`timestamps`**: байты **4–1023** = **255** encoded `uint32` BE (по умолчанию)
- [x] Байты 0–3: channel, `0x00`, uint16 counter
- [x] CH0/CH1: `encode_timestamp_ch01()`; CH2: `encode_timestamp_ch2()` + `--auto-toggle-edge`
- [x] CLI: `--events-per-packet`, `--event-step-ns`, `--marker-every-n-packets`
- [x] `verify_packets.py` + TECHNICAL.md обновлены
- [ ] README: схема Linux VM + bridged (кратко в TECHNICAL §8.2)

### P1 — осмысленный вывод для analyze.py

- [ ] Пресет CH2: **пары** триггеров (окна измерения)
- [ ] Пресет CH0: фотоны внутри окон (even/odd для signal/reference)
- [ ] Опционально: периодический маркер `0x00000000` (+100 ms) в потоке меток

### P2 — ближе к реальной плате (pcap)

- [ ] Общий счётчик пакетов между каналами (координатор / `multiprocessing`)
- [x] Парный режим ch0→ch1: `--dual-channel` (0 µs внутри пары, `--interval` между парами)
- [ ] Офлайн-верификатор: «255 слов, валидный decode, нет мусора»

---

## Фаза 2 — Сквозное тестирование

- [x] VM собрана (Ubuntu, bridged `enp0s3`, IP ~192.168.1.9)
- [x] odmr собран на VM (Python 3.14, `libplplot-dev`, `#include <Python.h>`)
- [x] Capture-only режим в `cv_odmr` (без Rigol/SpinCore) — приём UDP работает
- [x] Windows → VM: 100 пакетов, **100 enqueued**, 0 kernel drops
- [x] `wrong frame length: 46` — посторонний LAN-трафик (ARP/mDNS), не потеря наших пакетов
- [ ] `ch0_0.txt`: монотонные времена, правдоподобное число строк (полная проверка)
- [ ] На VM: `python analyze.py` → осмысленный `pulses_grouped.txt`
- [ ] Capture-only: корректный выход по Ctrl+C (`t1.join()`, без зависания после Ctrl+Z)

---

## Фаза 3 — 30‑минутный стресс‑тест потерь пакетов (HDD)

**Цель:** воспроизвести потери ~через 10 мин (как на реальной установке), записывая на HDD через существующий `odmr`, и локализовать причину.

### Что уже умеет `packet_collector` (`fpga2.c`)

| Счётчик | Что означает |
|---------|----------------|
| **packets enqueued** | Принято кадров 1066 байт |
| **kernel drops** | Потеря **до** userspace (переполнен RX ring ядра) |
| **enqueue failures** | Не хватило памяти на копию пакета в очередь (20000 слотов) |
| **write errors** | Ошибка записи на диск |
| **wrong frame length** | Посторонний трафик (ARP и т.д.), не наши UDP |

**Пробел:** проверка пропусков по **IP ID** (смещение `0x12` в кадре) есть в коде, но **логирование закомментировано** — при потере пакета не видно, *когда* и *сколько* пропало.

### Гипотеза «потери через ~10 мин на HDD»

```
Спаммер шлёт быстро
  → capture_thread кладёт пакеты в очередь (до 20000)
  → write_thread пишет ch0_0.txt (до 255 строк на пакет)
  → HDD не успевает
  → очередь заполняется, capture блокируется
  → переполняется kernel RX ring
  → kernel drops растут
```

Это **не** page cache — скорее **диск + объём записи**. При ~255 µs между пакетами за 30 мин ≈ **7 млн пакетов** и **десятки ГБ** в `ch0_0.txt`.

### Эксперимент на 30 минут

**Linux — приём и лог:**
```bash
cd ~/odmr
sudo ./cv_odmr enp0s3 2>&1 | tee ~/odmr/run_$(date +%Y%m%d_%H%M%S).log
```

**Параллельно (второй терминал) — нагрузка на диск:**
```bash
iostat -x 5
```

**Windows — отправка 30 минут (~255 µs, как плата):**
```powershell
cd C:\Users\dmitr\Desktop\udp_lab_sim
# 30 мин / 255 µs ≈ 7 058 824 пакетов
python udp_spammer.py `
  --dst-host 192.168.1.9 `
  --channel 0 `
  --timing fixed `
  --interval 255e-6 `
  --count 7058824 `
  2>&1 | Tee-Object -FilePath send_log.txt
```

Или `--count 0` и остановить через 30 мин — в конце `Total packets sent: N`.

**Независимая проверка (опционально, второй терминал VM):**
```bash
sudo tcpdump -i enp0s3 'udp port 4660' -w ~/odmr/capture_30min.pcap
tcpdump -r ~/odmr/capture_30min.pcap 2>/dev/null | wc -l
```

### Как понять, где потеря

| Сравнение | Вывод |
|-----------|--------|
| `sent` (Windows) = `packets enqueued` (Linux) | Потерь нет |
| `sent` > `enqueued`, **kernel drops > 0** | Перегрузка приёма (очередь / ring / CPU) |
| **enqueue failures > 0** | Нехватка RAM / malloc |
| **write errors > 0** | Диск / место / I/O |
| `iostat` %util ≈ 100%, await большой | HDD — узкое место |

**Главная метрика:** `потери = отправлено − packets enqueued` (+ смотреть **когда** выросли `kernel drops` в логе).

### Ускоренный тест гипотезы «HDD» (перед полными 30 мин)

```powershell
# A: тот же rate, 15 мин (~3.5M пакетов)
--count 3529412

# B: медленнее (1 ms) — если потерь нет, виноват I/O
--timing fixed --interval 1e-3 --count 30000
```

Если при 1 ms потерь нет, а при 255 µs через ~10 мин есть — почти наверняка **диск/очередь записи**.

### Доработки кода

- [x] **timestamp.py:** wrap coarse (26 bit) — длинный `timestamps` без struct.error
- [x] **udp_spammer.py:** `--dual-channel` (ch0→ch1, общий счётчик, пауза `--interval`)
- [x] **fpga2.c:** лог IP ID gap + periodic stats каждые 32768 кадров (stderr, fflush)
- [x] **odmr:** утилита `packet_capture` (без ini/Rigol/Python)
- [ ] **udp_spammer.py:** `--duration` / `--log-file` (опционально)
- [ ] **cv_odmr.cpp:** capture-only через `t1.join()` (на VM можно использовать `packet_capture`)

---

## Фаза 4 — Dual-channel + timestamps (как плата)

### Windows (отправитель)

Короткий тест (200 пакетов = 100 пар):

```powershell
cd C:\Users\dmitr\Desktop\udp_lab_sim
python udp_spammer.py --dst-host 192.168.1.9 --dual-channel --body-mode timestamps `
  --timing fixed --interval 255e-6 --count 200 2>&1 | Tee-Object send_dual.log
```

30 минут, два канала (~14.1M пакетов):

```powershell
# 1800 s / 255 µs × 2 канала ≈ 14 117 648
python udp_spammer.py --dst-host 192.168.1.9 --dual-channel --body-mode timestamps `
  --timing fixed --interval 255e-6 --count 14117648 2>&1 | Tee-Object send_dual_30min.log
```

### Linux (приём на HDD) — **корректный лог**

Скопировать на VM обновлённые: `fpga2.c`, `packet_capture.cpp`, `CMakeLists.txt`, пересобрать.

```bash
cd ~/odmr/build && make packet_capture
```

**Используйте `packet_capture`, не `cv_odmr`** — только захват, summary в stderr.

```bash
rm -f /mnt/hdd/ch0_*.txt /mnt/hdd/ch1_*.txt
cd /mnt/hdd
stdbuf -oL -eL sudo ~/odmr/packet_capture enp0s3 2>&1 | tee capture_$(date +%Y%m%d_%H%M%S).log
```

- Во время теста в логе появятся строки `packet_collector: enqueued=...` каждые ~32k кадров
- Остановка: **Ctrl+C** (не Ctrl+Z) → в конце `packet_collector summary`
- `2>&1 | tee` + `stdbuf` обязательны (summary идёт в stderr)

Проверка размера (на vboxsf `ls -lh` может не работать):

```bash
wc -l /mnt/hdd/ch0_0.txt /mnt/hdd/ch1_0.txt
du -h /mnt/hdd/ch0_0.txt
```

Ожидание для 100 пар: ~25500 строк в каждом файле; счётчики ch0/ch1 в payload шли 0,1,2,3…

### Чеклист перед стартом 30‑мин теста

- [ ] Достаточно места на HDD (`df -h ~/odmr` — нужны десятки ГБ при полном rate)
- [ ] Capture-only с корректным завершением
- [ ] stderr → `tee` в файл
- [ ] `iostat` в соседнем терминале
- [ ] Спаммер с фиксированным `--count` или лог `Total packets sent`
- [ ] После: сравнить sent vs enqueued vs kernel drops

---

## Справка: совместимость (текущее состояние)

| Параметр | udp_lab_sim сейчас | odmr ожидает |
|----------|-------------------|--------------|
| Размер кадра | 1024 B payload | **1066 B** Ethernet (Linux NIC) |
| Тело пакета | counter_fill / noise | **255 закодированных меток** с байта 4 |
| Канал | byte 0 `& 0x0F` | byte 0 `& 0x03` — **OK** |
| Проверка порядка | счётчик в payload | **IP ID** в кадре по смещению `0x12` (даёт ОС при send) |
| Платформа | Windows — OK | **только Linux** для приёмника |

### Главный разрыв (закрыт)

Режим `timestamps` в `udp_lab_sim` закрывает разрыв: bytes **4–1023** = 255 encoded меток. Legacy-режимы (`counter_fill`, `noise`) — только для Wireshark.

---

## Текущий статус (на 12.06.2026)

- [x] udp_lab_sim работает на Windows + Wireshark (loopback)
- [x] Формат пакетов: режим `timestamps` под odmr (TECHNICAL.md)
- [x] Linux VM, HDD через `/mnt/hdd`, 30‑мин тест 7M пакетов (counter_fill) — **OK**
- [x] Timestamp wrap + dual-channel + `packet_capture` + fpga2 stats
- [ ] Сквозной dual-channel тест с `timestamps` на HDD (Фаза 4)
