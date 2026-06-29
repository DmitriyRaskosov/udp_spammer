# udp_lab_sim — статус интеграции с odmr

**Актуально:** июнь 2026, ветка `home` в [odmr_test](https://github.com/DmitriyRaskosov/odmr_test).

Исторический пошаговый план (VM setup, HDD stress, `ch0_0.txt`, `Count` 7M+) удалён — он описывал устаревший контур.

---

## Схема (текущая)

```
Windows  udp_lab_sim (-CvOdmrProfile)  ──UDP 1066B──►  Ubuntu VM / стенд
                                                      packet_capture --analyze-stream
                                                      → runs/.../pulses_grouped.txt
```

- Сеть VM: bridged (`enp0s3`), не WSL2 для raw capture.
- Production **не пишет** `ch0_0.txt` / `analyze.py`.

---

## Стандартный тест

| Шаг | Где | Команда |
|-----|-----|---------|
| 1 | VM | `bash ~/odmr/scripts/run_stream.sh` |
| 2 | Windows | `.\scripts\spammer_odmr_compare.ps1 -CvOdmrProfile -DstHost 192.168.1.9` |
| 3 | VM | Ctrl+C после окончания спаммера |

Ожидание: 14 400 пакетов, 36 групп, `reorder late drops: 0`, `gap skips: 0`.

---

## Режимы спаммера

| Режим | Назначение |
|-------|------------|
| `-CvOdmrProfile` | Полный sweep из `cv_odmr.ini` (основной тест) |
| `-CvOdmrProfile -QuickTest` | 3×5 mini ini |
| `-Count 400` (без CvOdmr) | Короткий legacy smoke |
| `udp_spammer.py --odmr-pair --count N` | Непрерывный поток (soak / старые тесты) |

---

## Протокол

См. [TECHNICAL.md](TECHNICAL.md), [README.md](README.md).

`CvOdmrPairFactory`: sparse фотоны, один импульс на UDP-пару; padding нулей в хвосте payload (приёмник игнорирует хвостовые нули).

---

## Открыто

- [ ] Длинный soak (часы) с профилем, близким к cv_odmr
- [ ] Маркер границы частоты в analyze (сейчас — счёт импульсов из ini)
- [ ] Синхронизация `udp_lab_sim` branch `home` с GitHub
