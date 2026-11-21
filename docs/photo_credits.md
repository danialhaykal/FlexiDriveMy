# Catalog photo credits

Car photos come only from Wikimedia Commons, under a free licence (CC0, public domain, CC BY or CC BY-SA). Each car's `thumbnail_url` is the 1,280 px Commons thumbnail (the URL without its `utm_` tracking query), set through the audited admin API. The vehicle page links every Commons photo to its file page ("Photo: Wikimedia Commons"), which names the author and the licence; that link is worked out from the URL (`frontend/src/lib/wikimediaCredit.ts`), so nothing is keyed per car. No image file is stored in the repository.

| Car | Commons file | Author | Licence | Added |
|---|---|---|---|---|
| BMW 3 Series 320i Sport (#5) | [BMW G20 LCI 320i Alpine White (1).jpg](https://commons.wikimedia.org/wiki/File:BMW_G20_LCI_320i_Alpine_White_(1).jpg) | Damian B Oh | CC BY-SA 4.0 | 2026-10-26 |
| Mercedes-Benz C-Class C200 Avantgarde (#6) | [Mercedes-Benz C200 AVANTGARDE (W206) front.jpg](https://commons.wikimedia.org/wiki/File:Mercedes-Benz_C200_AVANTGARDE_(W206)_front.jpg) | Tokumeigakarinoaoshima | CC BY-SA 4.0 | 2026-10-26 |
| Lexus ES 250 Luxury (#7) | [LEXUS ES 250(ES 260) (XZ10) China (1).jpg](https://commons.wikimedia.org/wiki/File:LEXUS_ES_250(ES_260)_(XZ10)_China_(1).jpg) | Dinkun Chen | CC BY-SA 4.0 | 2026-10-26 |
| Porsche 911 Carrera (#12) | [2024 Porsche 911 992 Carrera.jpg](https://commons.wikimedia.org/wiki/File:2024_Porsche_911_992_Carrera.jpg) | Calreyn88 | CC BY-SA 4.0 | 2026-10-26 |
| Porsche Macan Base (#8) | [2022 Porsche Macan IMG 6376.jpg](https://commons.wikimedia.org/wiki/File:2022_Porsche_Macan_IMG_6376.jpg) | Alexander Migl | CC BY-SA 4.0 | 2026-10-26 |
| Porsche Macan Electric Macan RWD (#16) | [Porsche Macan 4 DSC 6050.jpg](https://commons.wikimedia.org/wiki/File:Porsche_Macan_4_DSC_6050.jpg) | Alexander-93 | CC BY-SA 4.0 | 2026-10-26 |
| Toyota Alphard 2.4 Executive Lounge (#17) | [Toyota ALPHARD Z (AGH40W).jpg](https://commons.wikimedia.org/wiki/File:Toyota_ALPHARD_Z_(AGH40W).jpg) | Tokumeigakarinoaoshima | CC BY-SA 4.0 | 2026-10-26 |
| Volvo XC60 B5 Core (#14) | [Volvo XC60 II FL2 T8 AWD Recharge PHEV Denim Blue Metallic 01.jpg](https://commons.wikimedia.org/wiki/File:Volvo_XC60_II_FL2_T8_AWD_Recharge_PHEV_Denim_Blue_Metallic_01.jpg) | Ethan Llamas | CC BY-SA 4.0 | 2026-10-26 |
| Volvo XC90 Ultra T8 (#13) | [2025 Volvo XC90 II Auto Zuerich 2024 DSC 6139.jpg](https://commons.wikimedia.org/wiki/File:2025_Volvo_XC90_II_Auto_Zuerich_2024_DSC_6139.jpg) | Alexander-93 | CC BY-SA 4.0 | 2026-10-26 |

**Note - Volvo XC90:** the first XC90 file's URL was longer than the 200-character `thumbnail_url` field, so a file with a shorter name was used.

Two candidate files were replaced after a visual check: the first Mercedes file was a rear view (`Mercedes-Benz_W206_IMG_5638.jpg`), and the first 911 file wore a racing livery (`2020_Porsche_911_992_Carrera_S.jpg`); a plain front three-quarter view from the same Commons category was used instead.
