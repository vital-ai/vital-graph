from nltk.corpus import framenet as fn

buy = fn.frame('Commerce_buy')
sell = fn.frame('Commerce_sell')
ct = fn.frame('Commercial_transaction')

buy_fes = set(buy.FE.keys())
sell_fes = set(sell.FE.keys())
ct_fes = set(ct.FE.keys())

print("Commerce_buy FEs:", sorted(buy_fes))
print()
print("Commerce_sell FEs:", sorted(sell_fes))
print()
print("Commercial_transaction FEs:", sorted(ct_fes))
print()
print("Shared buy+sell:", sorted(buy_fes & sell_fes))
print("Only in buy:", sorted(buy_fes - sell_fes))
print("Only in sell:", sorted(sell_fes - buy_fes))
print()

# Check FE-to-FE relations (inheritance mappings)
print("=== FE Relations for Commerce_buy ===")
for rel in buy.frameRelations:
    if hasattr(rel, 'feRelations'):
        for fer in rel.feRelations:
            sup = fer.superFE.name
            sub = fer.subFE.name
            supf = rel.superFrame.name
            subf = rel.subFrame.name
            rtype = rel.type.name
            print("  %s: %s (%s) <-> %s (%s)" % (rtype, sup, supf, sub, subf))

print()
print("=== FE Relations for Commerce_sell ===")
for rel in sell.frameRelations:
    if hasattr(rel, 'feRelations'):
        for fer in rel.feRelations:
            sup = fer.superFE.name
            sub = fer.subFE.name
            supf = rel.superFrame.name
            subf = rel.subFrame.name
            rtype = rel.type.name
            print("  %s: %s (%s) <-> %s (%s)" % (rtype, sup, supf, sub, subf))

print()
# How many unique FE names across ALL frames?
all_fe_names = set()
role_like = []
for frame in fn.frames():
    for fe in frame.FE.values():
        all_fe_names.add(fe.name)

print("Total unique FE names across all frames:", len(all_fe_names))

# Show the most common ones
from collections import Counter
fe_counts = Counter()
for frame in fn.frames():
    for fe in frame.FE.values():
        fe_counts[fe.name] += 1

print()
print("Most reused FE names (top 20):")
for name, count in fe_counts.most_common(20):
    print("  %4d frames: %s" % (count, name))

print()
print("FE names used in only 1 frame (first 20):")
singles = [n for n, c in fe_counts.items() if c == 1]
for name in sorted(singles)[:20]:
    print("  %s" % name)
print("  ... total single-use FEs:", len(singles))
