import sys

def modify_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Replace 1
    target1 = '''        self.slider_mask_blur.setValue(0)
        self.lbl_mask_blur = QtWidgets.QLabel("0 px")
        mask_blur_row.addWidget(self.slider_mask_blur)
        mask_blur_row.addWidget(self.lbl_mask_blur)
        mask_opt_layout.addLayout(mask_blur_row)
        
        stencil_row1 = QtWidgets.QHBoxLayout()'''
        
    replacement1 = '''        self.slider_mask_blur.setValue(0)
        self.lbl_mask_blur = QtWidgets.QLabel("0 px")
        mask_blur_row.addWidget(self.slider_mask_blur)
        mask_blur_row.addWidget(self.lbl_mask_blur)
        mask_opt_layout.addLayout(mask_blur_row)
        
        # Transform Controls
        transform_layout = QtWidgets.QHBoxLayout()
        transform_layout.addWidget(QtWidgets.QLabel("Transform: X/Y"))
        
        self.spin_mask_tx = QtWidgets.QDoubleSpinBox()
        self.spin_mask_tx.setRange(-4000.0, 4000.0)
        self.spin_mask_tx.setSingleStep(5.0)
        transform_layout.addWidget(self.spin_mask_tx)
        
        self.spin_mask_ty = QtWidgets.QDoubleSpinBox()
        self.spin_mask_ty.setRange(-4000.0, 4000.0)
        self.spin_mask_ty.setSingleStep(5.0)
        transform_layout.addWidget(self.spin_mask_ty)
        
        transform_layout.addWidget(QtWidgets.QLabel(" Scale:"))
        self.spin_mask_scale = QtWidgets.QDoubleSpinBox()
        self.spin_mask_scale.setRange(0.01, 10.0)
        self.spin_mask_scale.setValue(1.0)
        self.spin_mask_scale.setSingleStep(0.05)
        transform_layout.addWidget(self.spin_mask_scale)
        
        transform_layout.addWidget(QtWidgets.QLabel(" Rot:"))
        self.spin_mask_rotate = QtWidgets.QDoubleSpinBox()
        self.spin_mask_rotate.setRange(-360.0, 360.0)
        self.spin_mask_rotate.setSingleStep(1.0)
        transform_layout.addWidget(self.spin_mask_rotate)
        
        mask_opt_layout.addLayout(transform_layout)
        
        stencil_row1 = QtWidgets.QHBoxLayout()'''
        
    if target1 in content:
        content = content.replace(target1, replacement1)
    else:
        print('Target 1 not found')
        
    # Replace 2
    target2 = '''        self.slider_mask_feather.valueChanged.connect(self.on_mask_feather_changed)
        self.slider_mask_blend.valueChanged.connect(self.on_mask_blend_changed)
        self.slider_mask_blur.valueChanged.connect(self.on_mask_blur_changed)
        self.slider_mask_brush.valueChanged.connect(self.on_mask_brush_changed)
        self.slider_mask_ev.valueChanged.connect(self.on_mask_ev_slider_changed)'''
        
    replacement2 = '''        self.slider_mask_feather.valueChanged.connect(self.on_mask_feather_changed)
        self.slider_mask_blend.valueChanged.connect(self.on_mask_blend_changed)
        self.slider_mask_blur.valueChanged.connect(self.on_mask_blur_changed)
        self.slider_mask_brush.valueChanged.connect(self.on_mask_brush_changed)
        
        self.spin_mask_tx.valueChanged.connect(self.on_mask_transform_changed)
        self.spin_mask_ty.valueChanged.connect(self.on_mask_transform_changed)
        self.spin_mask_scale.valueChanged.connect(self.on_mask_transform_changed)
        self.spin_mask_rotate.valueChanged.connect(self.on_mask_transform_changed)
        
        self.slider_mask_ev.valueChanged.connect(self.on_mask_ev_slider_changed)'''
        
    if target2 in content:
        content = content.replace(target2, replacement2)
    else:
        print('Target 2 not found')
        
    # Replace 3
    target3 = '''        self.slider_mask_blend.blockSignals(True)
        self.slider_mask_blur.blockSignals(True)
        self.slider_mask_brush.blockSignals(True)
        self.slider_mask_ev.blockSignals(True)'''
        
    replacement3 = '''        self.slider_mask_blend.blockSignals(True)
        self.slider_mask_blur.blockSignals(True)
        self.slider_mask_brush.blockSignals(True)
        
        self.spin_mask_tx.blockSignals(True)
        self.spin_mask_ty.blockSignals(True)
        self.spin_mask_scale.blockSignals(True)
        self.spin_mask_rotate.blockSignals(True)
        
        self.slider_mask_ev.blockSignals(True)'''
        
    if target3 in content:
        content = content.replace(target3, replacement3)
    else:
        print('Target 3 not found')
        
    # Replace 4
    target4 = '''        self.slider_mask_blend.setValue(int(mask.blend * 100))
        self.lbl_mask_blend.setText(f"{int(mask.blend*100)} %")
        self.slider_mask_blur.setValue(int(mask.blur))
        self.lbl_mask_blur.setText(f"{int(mask.blur)} px")
        self.slider_mask_ev.setValue(int(mask.ev_offset * 100))'''
        
    replacement4 = '''        self.slider_mask_blend.setValue(int(mask.blend * 100))
        self.lbl_mask_blend.setText(f"{int(mask.blend*100)} %")
        self.slider_mask_blur.setValue(int(mask.blur))
        self.lbl_mask_blur.setText(f"{int(mask.blur)} px")
        
        self.spin_mask_tx.setValue(getattr(mask, 'offset_x', 0.0))
        self.spin_mask_ty.setValue(getattr(mask, 'offset_y', 0.0))
        self.spin_mask_scale.setValue(getattr(mask, 'scale', 1.0))
        self.spin_mask_rotate.setValue(getattr(mask, 'rotation', 0.0))
        
        self.slider_mask_ev.setValue(int(mask.ev_offset * 100))'''
        
    if target4 in content:
        content = content.replace(target4, replacement4)
    else:
        print('Target 4 not found')
        
    # Replace 5
    target5 = '''        self.slider_mask_blend.blockSignals(False)
        self.slider_mask_blur.blockSignals(False)
        self.slider_mask_brush.blockSignals(False)
        self.slider_mask_ev.blockSignals(False)'''
        
    replacement5 = '''        self.slider_mask_blend.blockSignals(False)
        self.slider_mask_blur.blockSignals(False)
        self.slider_mask_brush.blockSignals(False)
        
        self.spin_mask_tx.blockSignals(False)
        self.spin_mask_ty.blockSignals(False)
        self.spin_mask_scale.blockSignals(False)
        self.spin_mask_rotate.blockSignals(False)
        
        self.slider_mask_ev.blockSignals(False)'''
        
    if target5 in content:
        content = content.replace(target5, replacement5)
    else:
        print('Target 5 not found')
        
    # Replace 6
    target6 = '''    def on_browse_mask_image_clicked(self):'''
        
    replacement6 = '''    def on_mask_transform_changed(self):
        mask = self.get_active_mask()
        if mask:
            mask.offset_x = self.spin_mask_tx.value()
            mask.offset_y = self.spin_mask_ty.value()
            mask.scale = self.spin_mask_scale.value()
            mask.rotation = self.spin_mask_rotate.value()
            self._trigger_update()

    def on_browse_mask_image_clicked(self):'''
        
    if target6 in content:
        content = content.replace(target6, replacement6)
    else:
        print('Target 6 not found')
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

modify_file('e:/PROJECTS/HDRI_Match_Plate/hdri_match/ui/main_window.py')
print('Done!')
