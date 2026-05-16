import pandas as pd
df = pd.read_excel('C:/Users/fclub/WORDPERSSAUTO/keywords.xlsx')
row = df[df.iloc[:, 0].astype(str).str.contains('안쓰는', na=False)]
if not row.empty:
    with open('output.txt', 'w', encoding='utf-8') as f:
        f.write(str(row.iloc[-1]['본문원고']))
