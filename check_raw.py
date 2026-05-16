import pandas as pd
df = pd.read_excel('C:/Users/fclub/WORDPERSSAUTO/keywords.xlsx')
row = df[df.iloc[:, 0].astype(str).str.contains('보험', na=False)]
if not row.empty:
    with open('output_raw.txt', 'w', encoding='utf-8') as f:
        f.write(str(row.iloc[-1]['본문원고']))
