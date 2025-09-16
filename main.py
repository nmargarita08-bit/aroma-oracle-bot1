from pathlib import Path

CSV_PATH = os.getenv("OILS_CSV_PATH", "aroma_oracle_pack.csv")  # дефолт под твой файл
DB_PATH = os.getenv("DB_PATH", "aroma_bot.db")

def resolve_csv(path_str: str) -> str:
    p = Path(path_str)
    if p.exists():
        return str(p)
    base = Path(__file__).parent
    # пробуем типовые варианты и корень проекта
    for c in [base / path_str, base / "aroma_oracle_pack.csv", base / "aroma_oracle_pack_100.csv"]:
        if c.exists():
            return str(c)
    # отладка: покажем, что лежит рядом
    print("CWD:", os.getcwd())
    try:
        print("DIR:", os.listdir("."))
    except Exception:
        pass
    raise FileNotFoundError(f"CSV not found. Set OILS_CSV_PATH to actual filename. Tried: {path_str}")

def load_oils():
    global OILS
    OILS = []
    csv_file = resolve_csv(CSV_PATH)
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ...