import re

with open('e:/PROJECTS/HDRI_Match_Plate/hdri_match/ui/main_window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to find: self.lbl_xyz = QtWidgets.QLabel("...")
pattern = r'(self\.lbl_[a-zA-Z0-9_]+)\s*=\s*QtWidgets\.QLabel\("[^"]*"\)(?!\n\s*self\.lbl_[a-zA-Z0-9_]+\.setFixedWidth)'
def repl(m):
    lbl_name = m.group(1)
    return m.group(0) + f'\n        {lbl_name}.setFixedWidth(50)'

new_content, count = re.subn(pattern, repl, content)
if count > 0:
    with open('e:/PROJECTS/HDRI_Match_Plate/hdri_match/ui/main_window.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'Replaced {count} labels.')
else:
    print('No labels found.')
