# UDP Lab Simulator

Python-утилита для имитации UDP-потока лабораторной платы `192.168.10.10`.

Подробное описание протокола, временных меток и анализа pcap — в **[TECHNICAL.md](TECHNICAL.md)**.

---

## Требования

- Python 3.10+
- Только стандартная библиотека (без `pip install`)

---

## Быстрый старт

```powershell
cd ваш_путь\udp_lab_sim
python udp_spammer.py
```

Или двойной клик по `start_spammer.bat`.

По умолчанию:
- канал **0**, назначение `192.168.10.2:4660`
- payload **1024 байта**, счётчик с **0**
- неравномерные интервалы (`random`, 50 µs … 2 ms)
- бесконечная отправка (остановка: `Ctrl+C`)

---

## Команды запуска

### Базовые

```powershell
# Канал 0, значения по умолчанию
python udp_spammer.py

# Канал 1 (детектор #2)
python udp_spammer.py --channel 1

# Канал 2 (триггер), флаг фронта = 1
python udp_spammer.py --channel 2 --trigger-edge 1

# Отправить ровно 1000 пакетов и остановиться
python udp_spammer.py --count 1000

# Назначение — другой хост / порт
python udp_spammer.py --dst-host 192.168.10.5 --port 4660
```

### Тайминг отправки (сетевой уровень)

```powershell
# Фиксированный интервал 255 мкс (как в pcap между парами)
python udp_spammer.py --timing fixed --interval 255e-6

# Случайный неравномерный поток (по умолчанию)
python udp_spammer.py --timing random --random-min 50e-6 --random-max 2e-3

# Циклический список интервалов
python udp_spammer.py --timing list --interval-list "50e-6,255e-6,500e-6,1e-3,100e-6,2e-3"

# Без паузы между пакетами (максимальная скорость)
python udp_spammer.py --timing fixed --interval 0
```

### Временные метки в заголовке (логика платы)

```powershell
# Шаг метки 100 нс (по умолчанию)
python udp_spammer.py --ts-step-ns 100

# Начальное значение ts1 и смещение ts2
python udp_spammer.py --ts-base-ns 1000 --ts2-offset-ns 1000000
```

### Тело пакета (байты 12–1023)

```powershell
# Заполнение n, n+1, n+2... (по умолчанию)
python udp_spammer.py --body-mode counter_fill

# Счётчик в первых 4 байтах тела, остальное нули
python udp_spammer.py --body-mode counter

# Случайные данные
python udp_spammer.py --body-mode noise
```

### Сеть и IP источника

```powershell
# Привязка к конкретному интерфейсу (если IP 192.168.10.10 назначен на ПК)
python udp_spammer.py --bind-host 192.168.10.10

# Отправка на localhost для локального теста
python udp_spammer.py --dst-host 127.0.0.1
```

### Комбинированные примеры

```powershell
# Тест приёмника: канал 0, 500 пакетов, фиксированный интервал, как в pcap
python udp_spammer.py --channel 0 --count 500 --timing fixed --interval 255e-6 --dst-host 192.168.10.2

# Стресс-тест неравномерного потока
python udp_spammer.py --channel 0 --timing random --random-min 10e-6 --random-max 5e-3 --body-mode noise

# Триггер с чередованием фронта (вручную, два запуска)
python udp_spammer.py --channel 2 --trigger-edge 0 --count 100
python udp_spammer.py --channel 2 --trigger-edge 1 --count 100
```

### ODMR: photon (ch0) + trigger (ch2)

Режим для потокового анализа на приёмнике ([odmr_test](https://github.com/DmitriyRaskosov/odmr_test), ветка **`home`**).

**Production (online, без raw и без analyze.py):**

```powershell
# VM terminal 1:
#   cd ~/odmr && bash scripts/run_stream.sh

# Windows terminal 2 (after capture started):
.\scripts\spammer_odmr_compare.ps1 -CvOdmrProfile -DstHost 192.168.1.9
```

Профиль читает `cv_odmr.ini`: 36 частот × 100 повторов → 14 400 UDP-пакета, 36 строк в `pulses_grouped.txt`.

Быстрый smoke:

```powershell
.\scripts\spammer_odmr_compare.ps1 -CvOdmrProfile -QuickTest -DstHost 192.168.1.9
```

Короткий legacy-smoke (400 пар, без полного sweep):

```powershell
.\scripts\spammer_odmr_compare.ps1 -DstHost 192.168.1.9 -Count 400
```

На VM: `runs/.../pulses_grouped.txt` (`--analyze-stream`, параметры из `--experiment-ini`).

`analyze.py` и `--record-raw` на приёмнике — **только debug** (`scripts/verify_offline.sh`).

`--odmr-pair` / `--cv-odmr-profile`: ch0+ch2, общий uint16 counter с 0; ch2 auto-toggle-edge для even/odd.

**Длительные прогоны** (см. [TODO.md](TODO.md)):

```powershell
# 10 min — цикл sweep из cv_odmr.ini
.\scripts\spammer_odmr_compare.ps1 -LongCvOdmr -DurationSec 600 -DstHost 192.168.1.9

# 1 h — плотный OdmrPair (~28M пакетов)
.\scripts\spammer_odmr_compare.ps1 -SoakOdmrPair -DurationSec 3600 -DstHost 192.168.1.9
```

CLI: `--duration SEC` с `--odmr-pair`; `--cv-odmr-loop` с `--cv-odmr-profile`.

При длинных прогонах плотного потока (`OdmrPairFactory`) симулятор вставляет **+100 ms маркеры** при wrap coarse (~335 ms).

Проверка: `python verify_packets.py`

---

## Проверка без сети

Офлайн-валидация заголовков и размера payload:

```powershell
python verify_packets.py
```

Ожидаемый вывод: `OK: headers and payload size look correct`

---

## Wireshark

Захват на интерфейсе с адресом `192.168.10.10` (или на приёмнике).

Фильтр:

```
ip.src == 192.168.10.10 && udp.port == 4660 && frame.len == 1066
```

Проверки:

```
udp.length == 1032
udp.payload[1] == 00
```

---

## Параллельный запуск 3 каналов

Три отдельных процесса (каждый со своим счётчиком):

```powershell
# Терминал 1
python udp_spammer.py --channel 0 --bind-host 192.168.10.10

# Терминал 2
python udp_spammer.py --channel 1 --bind-host 192.168.10.10

# Терминал 3
python udp_spammer.py --channel 2 --bind-host 192.168.10.10 --trigger-edge 0
```

---

## Справка по аргументам

```powershell
python udp_spammer.py --help
```

| Аргумент | По умолчанию | Описание |
|----------|--------------|----------|
| `--channel` | `0` | Канал: 0, 1 или 2 |
| `--dst-host` | `192.168.10.2` | IP назначения |
| `--port` | `4660` | UDP-порт |
| `--bind-host` | *(пусто)* | Локальный IP для bind |
| `--count` | `0` | Число пакетов (0 = бесконечно) |
| `--body-mode` | `counter_fill` | `noise`, `counter`, `counter_fill` |
| `--timing` | `random` | `fixed`, `random`, `list` |
| `--interval` | `255e-6` | Интервал для `fixed` (секунды) |
| `--random-min` | `50e-6` | Мин. интервал для `random` |
| `--random-max` | `2e-3` | Макс. интервал для `random` |
| `--interval-list` | `50e-6,255e-6,...` | Список для `list` |
| `--ts-base-ns` | `1000` | Начальная метка ts1 (нс) |
| `--ts2-offset-ns` | `1000000` | Смещение ts2 от ts1 (нс) |
| `--ts-step-ns` | `100` | Шаг меток на пакет (нс) |
| `--trigger-edge` | `0` | Флаг фронта для канала 2 |
| `--odmr-pair` | *(выкл.)* | Чередовать ch0→ch2 для ODMR (photon + trigger) |
| `--dual-channel` | *(выкл.)* | Чередовать ch0→ch1 (взаимоисключающе с `--odmr-pair`) |

---

## Структура проекта

| Файл | Назначение |
|------|------------|
| [TECHNICAL.md](TECHNICAL.md) | Техническая документация протокола |
| `udp_spammer.py` | Основной скрипт |
| `timestamp.py` | Кодирование временных меток |
| `packet.py` | Сборка payload |
| `timing.py` | Неравномерные интервалы |
| `verify_packets.py` | Офлайн-проверка |
| `start_spammer.bat` | Быстрый запуск |
