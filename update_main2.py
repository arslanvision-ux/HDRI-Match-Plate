import sys

def modify_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Replace 1
    target1 = '''        self.viewer_left.sunMoved.connect(self.on_sun_moved)'''
        
    replacement1 = '''        self.viewer_left.sunMoved.connect(self.on_sun_moved)
        self.viewer_left.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_left.transformDragged.connect(self.on_transform_dragged)
        self.viewer_right.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_right.transformDragged.connect(self.on_transform_dragged)'''
        
    if target1 in content:
        content = content.replace(target1, replacement1)
    else:
        print('Target 1 not found')
        
    # Replace 2
    target2 = '''    def on_mask_transform_changed(self):'''
        
    replacement2 = '''    def on_transform_drag_started(self):
        mask = self.get_active_mask()
        if mask:
            self._drag_start_tx = getattr(mask, 'offset_x', 0.0)
            self._drag_start_ty = getattr(mask, 'offset_y', 0.0)
            self._drag_start_scale = getattr(mask, 'scale', 1.0)
            self._drag_start_rotate = getattr(mask, 'rotation', 0.0)

    def on_transform_dragged(self, mode, dx, dy):
        mask = self.get_active_mask()
        if mask and hasattr(self, '_drag_start_tx'):
            if mode == "Translate":
                self.spin_mask_tx.setValue(self._drag_start_tx + dx)
                self.spin_mask_ty.setValue(self._drag_start_ty + dy)
            elif mode == "Scale":
                delta = (dx - dy) * 0.005
                self.spin_mask_scale.setValue(max(0.01, self._drag_start_scale + delta))
            elif mode == "Rotate":
                delta = (dx - dy) * 0.5
                self.spin_mask_rotate.setValue(self._drag_start_rotate + delta)

    def on_mask_transform_changed(self):'''
        
    if target2 in content:
        content = content.replace(target2, replacement2)
    else:
        print('Target 2 not found')
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

modify_file('e:/PROJECTS/HDRI_Match_Plate/hdri_match/ui/main_window.py')
print('Done!')
