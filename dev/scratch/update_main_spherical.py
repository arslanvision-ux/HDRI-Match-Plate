import re
with open(r'e:\PROJECTS\HDRI_Match_Plate\hdri_match\ui\main_window.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    "self.chk_inpaint_key_green.blockSignals(True)\n        self.chk_custom_wf.blockSignals(True)",
    "self.chk_inpaint_key_green.blockSignals(True)\n        self.chk_spherical_proj.blockSignals(True)\n        self.chk_custom_wf.blockSignals(True)"
)

content = content.replace(
    "self.chk_inpaint_key_green.setChecked(getattr(mask, 'inpaint_key_green', False))\n        \n        # Load Custom Workflow Settings",
    "self.chk_inpaint_key_green.setChecked(getattr(mask, 'inpaint_key_green', False))\n        self.chk_spherical_proj.setChecked(getattr(mask, 'spherical_projection', False))\n        \n        # Load Custom Workflow Settings"
)

content = content.replace(
    "self.chk_inpaint_key_green.blockSignals(False)\n        self.chk_custom_wf.blockSignals(False)",
    "self.chk_inpaint_key_green.blockSignals(False)\n        self.chk_spherical_proj.blockSignals(False)\n        self.chk_custom_wf.blockSignals(False)"
)

content = content.replace(
    "mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()\n        \n        mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()",
    "mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()\n        mask.spherical_projection = self.chk_spherical_proj.isChecked()\n        \n        mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()"
)

content = content.replace(
    "mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()\n            \n            mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()",
    "mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()\n            mask.spherical_projection = self.chk_spherical_proj.isChecked()\n            \n            mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()"
)

with open(r'e:\PROJECTS\HDRI_Match_Plate\hdri_match\ui\main_window.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated main_window.py successfully.")
