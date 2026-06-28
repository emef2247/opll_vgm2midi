# vgm2midi

YM2413 / OPLL を使用した VGM ファイルを  
Standard MIDI File（SMF Format 0）へ変換するツールです。

FM メロディ（ch0–8）と OPLL リズム（BD/SD/TOM/TC/HH/CYM）を解析し、  
**General MIDI（GM）** または **Yamaha TX802** 向けの MIDI データを生成します。

---

## 特徴

- YM2413（OPLL）の FM チャンネルを MIDI ノートへ変換  
- OPLL リズムを GM または RX21 ドラムノートへ変換  
- BPM を VGM から自動検出  
- ポルタメント（is_portamento=1）を MIDI CC84/65/5 で再現  
- inst=0（ユーザー音色）は JSON に保存し、再変換時に反映  
- GM / TX802 のどちらにも対応  
- melody_mode による **2 種類の音色マッピングルール**  
  - default：OPLLの音色の特徴を考慮した変換テーブル
  - name：音名ベースのマッピング  

---

## インストール

Python 3.10 以上を推奨。

```bash
git clone https://github.com/xxxx/vgm2midi
cd vgm2midi
pip install -r requirements.txt
```

---

## 使い方

```bash
python vgm2midi.py [オプション] <入力VGMファイル>
```

### 出力ファイル

| ファイル | 説明 |
|---------|------|
| `<stem>.mid` | 生成された MIDI ファイル（SMF Format 0） |
| `<stem>.user_voice.json` | inst=0 のユーザー音色マッピング（必要時のみ生成） |

---

## 主なオプション

| オプション | 説明 |
|-----------|------|
| `--target {gm,tx802}` | 出力先音源（デフォルト: gm） |
| `--melody_mode {default,name}` | メロディ音色のマッピング方式 |
| `--rhythm_mode {gm,rx21}` | リズムマッピング方式 |
| `--outdir DIR` | 出力ディレクトリ |
| `--ppq N` | MIDI PPQ（デフォルト: 480） |
| `--debug` | 中間 CSV を保持し詳細ログを表示 |

---

## --target {gm,tx802}

出力先音源を選択します。

- **gm**  
  標準 GM 音源向けの MIDI を生成（デフォルト）

- **tx802**  
  Yamaha TX802 向けに Bank Select + Program Change を出力  
  TX802 のプリセット A/B を使用した音色マッピングを行う

---

## --melody_mode {default,name}

OPLL の FM メロディ音色を GM/TX802 に割り当てる方式を選択します。

### **default**
TX802:
OPLL の音色の各パラメータとTX802のプリセット A/Bの各パラメータ間の最短距離を計算し、最も距離が近いものTOP3から選定した変換テーブルを使用
ユーザパッチも同様にTX802のプリセット A/Bから最も距離が近いものを選択

GM:
--target=tx802, --melody_mode=defaultで選出された音色をリファレンスとして、GMの音色を選出

### **name**
プリセットの音色の名前ベースでの対応付け

---

## --rhythm_mode {gm,rx21}

OPLL リズムのマッピング方式を選択します。

- **gm**  
  GM ドラムノートにマッピング  
  TOM / HH / TC は OPLL の scale に応じて可変

- **rx21**  
  Yamaha RX21 のドラムパッドにマッピング  
  scale に応じて音程が変化

---

## 出力ファイル名の命名規則
```
<stem>_<postfix>.mid
```
- <stem> … 入力ファイル名のベース部分

- <postfix> … target / melody_mode / rhythm_mode の組み合わせで決定

## postfix 対応表
| target | melody_mode | rhythm_mode | postfix |
| --- | --- | --- | --- |
| tx802 | default | gm | ``_default_gm`` |
| tx802 | default | rx21 | ``_default_rx21`` |
| tx802 | name | gm | ``_name_gm`` |
| tx802 | name | rx21 | ``_name_rx21`` |
| gm | default | gm | ``_default_gm`` |
| gm | default | rx21 | ``_default_r21`` |
| gm | name | gm | ``_name_gm`` |
| gm | name | rx21 | ``_name_rx21`` |
---

## 使用例

### 1. GM 用に変換（デフォルト）

```bash
python vgm2midi.py mysong.vgm
```

### 2. TX802 用に変換 (--melody_mode=default : OPLL の音色性格を再現したマッピングで変換)

```bash
python vgm2midi.py --target=tx802 mysong.vgm
```

### 3.  音名に忠実なマッピングで変換

```bash
python vgm2midi.py --melody_mode=name mysong.vgm
```

### 4. RX21 リズムマッピングを使用

```bash
python vgm2midi.py --rhythm_mode=rx21 mysong.vgm
```

### 5. 出力先ディレクトリを指定

```bash
python vgm2midi.py --outdir=./out mysong.vgm
```

---

## ユーザー音色（inst=0）について

変換時に inst=0 の音色が検出されると、  
`<stem>.user_voice.json` が生成されます。

- GM モードでは GM Program 番号を指定  
- TX802 モードでは Bank(A or B) / Voice 番号を指定  

JSON を編集して再度変換すると、指定した音色が反映されます。  
既存の JSON は上書きされません。

---

## ライセンス

MIT License

---
# vgm2midi

`vgm2midi` converts VGM files using YM2413 / OPLL into  
Standard MIDI File (SMF Format 0).

It analyzes FM melody channels (ch0–8) and OPLL rhythm (BD / SD / TOM / TC / HH / CYM),  
and generates MIDI data for **General MIDI (GM)** or **Yamaha TX802**.

---

## Features

- Converts YM2413 (OPLL) FM channels into MIDI notes  
- Converts OPLL rhythm into GM or RX21 drum notes  
- Automatically detects BPM from the VGM stream  
- Portamento (`is_portamento=1`) reproduced using CC84 / CC65 / CC5  
- `inst=0` (user patches) are saved into JSON and reused on subsequent conversions  
- Supports both GM and TX802 output  
- Two melody‑mapping modes:  
  - **default** — mapping based on OPLL timbral characteristics  
  - **name** — mapping based on instrument names  

---

## Installation

Python 3.10+ recommended.

```bash
git clone https://github.com/xxxx/vgm2midi
cd vgm2midi
pip install -r requirements.txt
```

---

## Usage

```bash
python vgm2midi.py [options] <input.vgm>
```

### Output Files

| File | Description |
|------|-------------|
| `<stem>.mid` | Generated MIDI file (SMF Format 0) |
| `<stem>.user_voice.json` | User‑patch mapping (created only when inst=0 is used) |

---

## Main Options

| Option | Description |
|--------|-------------|
| `--target {gm,tx802}` | Output sound module (default: gm) |
| `--melody_mode {default,name}` | Melody‑voice mapping method |
| `--rhythm_mode {gm,rx21}` | Rhythm mapping method |
| `--outdir DIR` | Output directory |
| `--ppq N` | MIDI PPQ (default: 480) |
| `--debug` | Keep intermediate CSV and show detailed logs |

---

## --target {gm,tx802}

Select the output sound module.

### **gm**
Generates standard GM‑compatible MIDI output (default).

### **tx802**
Outputs Bank Select + Program Change for Yamaha TX802.  
Uses TX802 preset banks A/B and applies OPLL→TX802 timbre mapping.

---

## --melody_mode {default,name}

Select how OPLL FM melody voices are mapped to GM or TX802 instruments.

### **default**

#### TX802
Uses a parameter‑distance–based mapping:

- Computes the shortest parameter distance between each OPLL preset and all TX802 A/B presets  
- Builds a conversion table from the closest **TOP 3** candidates  
- User patches (inst=0) are also matched to the nearest TX802 preset

#### GM
GM program numbers are selected **based on the TX802 result**:

- The GM instrument is chosen by referencing the TX802 voice selected under  
  `--target=tx802 --melody_mode=default`  
- GM mapping follows the timbral category implied by the TX802 default mapping

### **name**
Name‑based mapping:

- Each OPLL instrument number is mapped directly to the corresponding GM program  
- Follows GM naming conventions; does not use TX802 timbral characteristics

---

## --rhythm_mode {gm,rx21}

Select rhythm mapping.

### **gm**
Maps OPLL rhythm to GM drum notes.  
TOM / HH / TC vary depending on OPLL `scale`.

### **rx21**
Maps OPLL rhythm to Yamaha RX21 drum layout.  
Pitch varies depending on `scale`.

---

## Output Filename Format

```
<stem>_<postfix>.mid
```

- `<stem>` — base name of the input file  
- `<postfix>` — determined by `target`, `melody_mode`, and `rhythm_mode`

### Postfix Table

| target | melody_mode | rhythm_mode | postfix |
|--------|-------------|-------------|---------|
| tx802 | default | gm | `_default_gm` |
| tx802 | default | rx21 | `_default_rx21` |
| tx802 | name | gm | `_name_gm` |
| tx802 | name | rx21 | `_name_rx21` |
| gm | default | gm | `_default_gm` |
| gm | default | rx21 | `_default_rx21` |
| gm | name | gm | `_name_gm` |
| gm | name | rx21 | `_name_rx21` |

---

## Examples

### 1. Convert to GM (default)

```bash
python vgm2midi.py mysong.vgm
```

### 2. Convert for TX802 (default OPLL‑timbre mapping)

```bash
python vgm2midi.py --target=tx802 mysong.vgm
```

### 3. Convert using name‑based mapping

```bash
python vgm2midi.py --melody_mode=name mysong.vgm
```

### 4. Use RX21 rhythm mapping

```bash
python vgm2midi.py --rhythm_mode=rx21 mysong.vgm
```

### 5. Specify output directory

```bash
python vgm2midi.py --outdir=./out mysong.vgm
```

---

## User Patches (inst=0)

When inst=0 is detected,  
`<stem>.user_voice.json` is created.

- In **GM mode**: specify GM Program numbers  
- In **TX802 mode**: specify Bank (A/B) and Voice numbers  

Editing the JSON and re‑running the conversion applies your custom mapping.  
Existing JSON files are never overwritten.

---

## License

MIT License
