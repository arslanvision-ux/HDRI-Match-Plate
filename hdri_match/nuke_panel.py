import os
try:
    from hdri_match.ui.qt_shim import QtWidgets, QtCore
    from hdri_match.ui.main_window import HdriCalibWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False

class NukeHdriPanel(QtWidgets.QWidget if HAS_QT else object):
    def __init__(self, parent=None):
        super(NukeHdriPanel, self).__init__(parent)
        if not HAS_QT:
            return
            
        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        
        # Create the main window, but don't show it as a standalone window
        self.main_window = HdriCalibWindow(parent=self)
        
        # Setup top layout for Nuke controls
        self.nuke_controls_layout = QtWidgets.QHBoxLayout()
        
        # Live link checkbox
        self.chk_live_link = QtWidgets.QCheckBox("Live Link to Node Graph")
        self.chk_live_link.setStyleSheet("color: #ffaa00; font-weight: bold; padding: 5px;")
        self.chk_live_link.setToolTip("When checked, UI adjustments automatically update existing exported nodes.")
        self.chk_live_link.setChecked(True)
        
        # Send to Nuke button
        self.btn_send_nuke = QtWidgets.QPushButton("Send Setup to Nuke")
        self.btn_send_nuke.setStyleSheet("background-color: #d86c00; color: #fff; font-weight: bold; padding: 5px;")
        self.btn_send_nuke.setToolTip("Generates the full HDRI calibration node tree and inserts it directly into the Nuke node graph.")
        self.btn_send_nuke.clicked.connect(self.send_setup_to_nuke)
        
        self.nuke_controls_layout.addWidget(self.btn_send_nuke)
        self.nuke_controls_layout.addWidget(self.chk_live_link)
        self.nuke_controls_layout.addStretch()
        
        # Add to the panel layout at the top
        self.layout().addLayout(self.nuke_controls_layout)
        
        # Set window flags so it behaves like a child widget, not a top-level window
        self.main_window.setWindowFlags(QtCore.Qt.Widget)
        
        # Add the main window directly to our panel layout
        self.layout().addWidget(self.main_window)
        
        # Hook into the pipeline update mechanism
        original_trigger = self.main_window._trigger_update
        def hooked_update(*args, **kwargs):
            original_trigger(*args, **kwargs)
            if self.chk_live_link.isChecked():
                self.push_to_nuke_live()
        self.main_window._trigger_update = hooked_update
        
    def send_setup_to_nuke(self):
        """Generates the Nuke script and pastes it directly into the Nuke node graph."""
        try:
            import nuke
            from hdri_match.io.nuke_export import export_nuke_nodes
            
            st = self.main_window.pipeline.state
            nk_script = export_nuke_nodes(st)
            
            # Use clipboard to pass to Nuke's nodePaste
            from hdri_match.ui.qt_shim import QtWidgets
            clipboard = QtWidgets.QApplication.clipboard()
            old_text = clipboard.text()
            
            # Wrap the exported script in a Group so we can safely rebuild its contents
            group_name = "HDRI_Match_Calibration"
            grp = nuke.toNode(group_name)
            
            reformat_mode = self.main_window.combo_reformat.currentText()
            target_w, target_h = None, None
            
            if reformat_mode == "Match Plate" and hasattr(st, 'plate_array') and st.plate_array is not None:
                target_h, target_w = st.plate_array.shape[:2]
            elif "x" in reformat_mode:
                try:
                    target_w, target_h = map(int, reformat_mode.split("x"))
                except ValueError:
                    pass
            
            if not grp:
                # Create the Group from scratch along with Read nodes
                for n in nuke.allNodes():
                    n['selected'].setValue(False)
                    
                if target_w and target_h:
                    try:
                        nuke.addFormat(f"{target_w} {target_h} 1.0 HDRI_Match_Format")
                    except Exception:
                        pass
                        
                if st.plate_path:
                    plate_read = nuke.createNode("Read", f"file {{{st.plate_path.replace(chr(92), '/')}}}")
                    plate_read['name'].setValue("Reference_Plate")
                    plate_read['selected'].setValue(False)
                    
                    if target_w and target_h:
                        plate_reformat = nuke.createNode("Reformat")
                        plate_reformat['format'].setValue("HDRI_Match_Format")
                        plate_reformat.setInput(0, plate_read)
                        plate_reformat['selected'].setValue(False)
                        last_plate = plate_reformat
                    else:
                        last_plate = plate_read
                        
                    plate_ev = nuke.createNode("EXPTool")
                    plate_ev['name'].setValue("Reference_Plate_EV")
                    plate_ev['mode'].setValue("Stops")
                    plate_ev.setInput(0, last_plate)
                    plate_ev['selected'].setValue(False)
                    plate_ev['red'].setValue(getattr(st, 'plate_ev_offset', 0.0))
                    plate_ev['green'].setValue(getattr(st, 'plate_ev_offset', 0.0))
                    plate_ev['blue'].setValue(getattr(st, 'plate_ev_offset', 0.0))
                        
                    plate_sat = nuke.createNode("ColorCorrect")
                    plate_sat['name'].setValue("Reference_Plate_Sat")
                    plate_sat['saturation'].setValue(getattr(st, 'plate_saturation', 1.0))
                    plate_sat.setInput(0, plate_ev)
                    plate_sat['selected'].setValue(False)
                    
                    plate_temp = nuke.createNode("Multiply")
                    plate_temp['name'].setValue("Reference_Plate_TempTint")
                    plate_temp.setInput(0, plate_sat)
                    plate_temp['selected'].setValue(False)
                    
                    # Compute initial Temp/Tint values
                    temp = getattr(st, 'plate_temperature', 0.0)
                    tint = getattr(st, 'plate_tint', 0.0)
                    r_scale = max(0.01, 1.0 + temp + tint)
                    g_scale = max(0.01, 1.0 - tint)
                    b_scale = max(0.01, 1.0 - temp)
                    lum = (r_scale + g_scale + b_scale) / 3.0
                    plate_temp['value'].setValue([r_scale/lum, g_scale/lum, b_scale/lum, 1.0])
                if st.hdri_path:
                    hdri_read_path = st.hdri_path
                    if getattr(st, 'sun_relight_enable', False) and hasattr(st, 'original_hdri'):
                        try:
                            import os
                            import tempfile
                            from hdri_match.io.exporter import save_numpy_to_image
                            
                            temp_dir = tempfile.gettempdir()
                            patched_path = os.path.join(temp_dir, "hdri_match_live_sun.exr")
                            # Apply sun relight to raw hdri
                            patched_img = self.main_window.pipeline.apply_sun_relighting(st.original_hdri.copy())
                            save_numpy_to_image(patched_img, patched_path)
                            hdri_read_path = patched_path
                            print(f"Baked Sun Relighting to {patched_path}")
                        except Exception as e:
                            print(f"Failed to bake sun relighting: {e}")

                    hdri_read = nuke.createNode("Read", f"file {{{hdri_read_path.replace(chr(92), '/')}}}")
                    hdri_read['name'].setValue("Source_HDRI")
                    
                    if target_w and target_h:
                        hdri_reformat = nuke.createNode("Reformat")
                        hdri_reformat['format'].setValue("HDRI_Match_Format")
                        hdri_reformat.setInput(0, hdri_read)
                        hdri_reformat['selected'].setValue(True)
                    
                grp = nuke.createNode("Group", f"name {group_name}")
                grp.begin()
                
                # Inside the new group
                input_node = nuke.createNode("Input", "name HDRI_In")
                clipboard.setText(nk_script)
                nuke.nodePaste("%clipboard%")
                
                # Find the last node pasted (N_Calibrated or similar) to connect to output
                # export_nuke_nodes ends with the final node selected
                out_node = nuke.createNode("Output", "name Out")
                grp.end()
            else:
                # Group exists, just rebuild its internals!
                grp.begin()
                # Delete everything except Input and Output
                for n in nuke.allNodes():
                    if n.Class() not in ["Input", "Output"]:
                        nuke.delete(n)
                
                in_node = nuke.toNode("HDRI_In")
                if in_node:
                    in_node['selected'].setValue(True)
                
                clipboard.setText(nk_script)
                nuke.nodePaste("%clipboard%")
                
                out_node = nuke.toNode("Out")
                if out_node:
                    # Connect out node to whatever is currently selected (last pasted node)
                    sel = nuke.selectedNode()
                    if sel:
                        out_node.setInput(0, sel)
                grp.end()
            
            # --- CG LOOKDEV MATCH EXPORT ---
            if getattr(st, 'cg_lights', None) and getattr(st, 'cg_exr_path', None):
                from hdri_match.io.nuke_export import export_cg_nuke_nodes
                cg_script = export_cg_nuke_nodes(st)
                if cg_script:
                    cg_grp_name = "CG_Lookdev_Match"
                    cg_grp = nuke.toNode(cg_grp_name)
                    
                    if not cg_grp:
                        for n in nuke.allNodes():
                            n['selected'].setValue(False)
                        cg_grp = nuke.createNode("Group", f"name {cg_grp_name}")
                        cg_grp.begin()
                        clipboard.setText(cg_script)
                        nuke.nodePaste("%clipboard%")
                        out_node = nuke.createNode("Output", "name Out")
                        cg_grp.end()
                    else:
                        cg_grp.begin()
                        for n in nuke.allNodes():
                            if n.Class() != "Output":
                                nuke.delete(n)
                        clipboard.setText(cg_script)
                        nuke.nodePaste("%clipboard%")
                        out_node = nuke.toNode("Out")
                        if out_node:
                            sel = nuke.selectedNode()
                            if sel:
                                out_node.setInput(0, sel)
                        cg_grp.end()
            
            clipboard.setText(old_text)            
        except Exception as e:
            import traceback
            traceback.print_exc()
            from hdri_match.ui.qt_shim import QtWidgets
            QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to send to Nuke:\n{e}")
            
    def push_to_nuke_live(self):
        """Live updates the Nuke node graph if the nodes exist."""
        try:
            import nuke
        except ImportError:
            return
            
        grp = nuke.toNode("HDRI_Match_Calibration")
        if not grp:
            return
            
        st = self.main_window.pipeline.state
        needs_rebuild = False
        
        # Check if structural rebuild is needed
        if getattr(st, 'masks', None):
            for i, mask in enumerate(st.masks):
                if mask.enabled:
                    if not grp.node(f"Mask_{i+1}_Shape"):
                        needs_rebuild = True
                        break
                    if getattr(mask, 'blur', 0.0) > 0.5 and not grp.node(f"Mask_{i+1}_Blur"):
                        needs_rebuild = True
                        break
                    if getattr(mask, 'stencil_enable', False) and not grp.node(f"Mask_{i+1}_Stencil"):
                        needs_rebuild = True
                        break
                    m_mode = getattr(mask, 'mode', 'Grade')
                    if m_mode == "Solid Fill" and not grp.node(f"Mask_{i+1}_Fill"):
                        needs_rebuild = True
                        break
                    if m_mode == "Chroma Replace" and not grp.node(f"Mask_{i+1}_ChromaKey"):
                        needs_rebuild = True
                        break
                    
        if getattr(st, 'horizon_enable', False) and not grp.node("HDRI_Ground_Mask"):
            needs_rebuild = True
            
        if needs_rebuild:
            self.send_setup_to_nuke()
            return
            
        # 1. Update EV Offset and Black Offset
        node_ev = grp.node("HDRI_EV_Offset")
        if node_ev:
            ev = st.ev_offset if getattr(st, 'apply_exposure_match', False) else 0.0
            node_ev['red'].setValue(ev)
            node_ev['green'].setValue(ev)
            node_ev['blue'].setValue(ev)
            
        node_black = grp.node("HDRI_Black_Offset")
        if node_black:
            bo = st.black_offset if getattr(st, 'apply_exposure_match', False) else 0.0
            node_black['value'].setValue(bo)
            
        # 2. Update Temp/Tint
        node_temp = grp.node("HDRI_TempTint")
        if node_temp:
            r_scale = max(0.01, 1.0 + st.temperature + st.tint)
            g_scale = max(0.01, 1.0 - st.tint)
            b_scale = max(0.01, 1.0 - st.temperature)
            lum = (r_scale + g_scale + b_scale) / 3.0
            
            cr = r_scale / lum
            cg = g_scale / lum
            cb = b_scale / lum
            
            node_temp['value'].setValue([cr, cg, cb, 1.0])
            
        # 3. Update Yaw Rotation
        node_yaw = grp.node("HDRI_Yaw_Rotation")
        if node_yaw:
            # Update the offset variable in the Expression node
            yaw = getattr(st, 'hdri_yaw', 0.0)
            expr = f"({yaw}/360.0)*width"
            node_yaw['temp_expr0'].setValue(expr)
            
        # 4. Update Masks
        if getattr(st, 'masks', None):
            for i, mask in enumerate(st.masks):
                # Shape
                node_shape = grp.node(f"Mask_{i+1}_Shape")
                if node_shape and mask.rect is not None:
                    nx1, ny1, nx2, ny2 = mask.rect
                    nx1, nx2 = min(nx1, nx2), max(nx1, nx2)
                    ny1, ny2 = min(ny1, ny2), max(ny1, ny2)
                    if mask.shape == "Ellipse":
                        cx = (nx1 + nx2) / 2.0
                        cy = 1.0 - (ny1 + ny2) / 2.0
                        rx = max((nx2 - nx1) / 2.0, 1e-5)
                        ry = max((ny2 - ny1) / 2.0, 1e-5)
                        node_shape['expr3'].setValue(f"pow((x/width - {cx:.5f})/{rx:.5f}, 2) + pow((y/height - {cy:.5f})/{ry:.5f}, 2) <= 1.0 ? 1.0 : 0.0")
                    else:
                        y_min = 1.0 - ny2
                        y_max = 1.0 - ny1
                        node_shape['expr3'].setValue(f"x/width >= {nx1:.5f} && x/width <= {nx2:.5f} && y/height >= {y_min:.5f} && y/height <= {y_max:.5f} ? 1.0 : 0.0")
                
                # Feather
                node_feather = grp.node(f"Mask_{i+1}_Feather")
                if node_feather:
                    node_feather['size'].setValue(getattr(mask, 'feather', 0.0))
                    
                # Blur
                node_blur = grp.node(f"Mask_{i+1}_Blur")
                if node_blur:
                    node_blur['size'].setValue(getattr(mask, 'blur', 0.0))
                    
                # Stencil
                node_stencil = grp.node(f"Mask_{i+1}_Stencil")
                if node_stencil:
                    mode = getattr(mask, 'stencil_mode', 'Luminance')
                    invert = getattr(mask, 'stencil_invert', False)
                    thresh = getattr(mask, 'stencil_threshold', 0.5)
                    
                    if mode == "Luminance":
                        expr = "0.2126*r + 0.7152*g + 0.0722*b"
                    elif mode == "Green Key":
                        expr = "g - max(r, b)"
                    else:
                        expr = "b - max(r, g)"
                        
                    inv_str = "1.0 - " if invert else ""
                    node_stencil['temp_expr0'].setValue(expr)
                    node_stencil['temp_expr1'].setValue(str(thresh))
                    node_stencil['expr3'].setValue(f"clamp({inv_str}(key - t) * 10.0 + 0.5, 0.0, 1.0)")

                mode = getattr(mask, 'mode', 'Grade')
                if mode == "Solid Fill":
                    node_fill = grp.node(f"Mask_{i+1}_Fill")
                    if node_fill:
                        r, g, b = getattr(mask, 'fill_color', (0.18, 0.18, 0.18))
                        node_fill['color'].setValue([r, g, b, 0.0])
                elif mode == "Chroma Replace":
                    node_chroma = grp.node(f"Mask_{i+1}_ChromaKey")
                    if node_chroma:
                        is_green = getattr(mask, 'chroma_hue', 120.0) < 180
                        tol = getattr(mask, 'chroma_tolerance', 0.5)
                        edge0 = max(0.01, 1.0 - tol)
                        delta = max(edge0 + 0.2 - edge0, 1e-6)
                        key_expr = "g - max(r,b)" if is_green else "b - max(r,g)"
                        node_chroma['temp_expr0'].setValue(key_expr)
                        node_chroma['temp_expr3'].setValue(f"clamp((key_norm - {edge0}) / {delta}, 0.0, 1.0)")
                        
                    node_chroma_fill = grp.node(f"Mask_{i+1}_ChromaFill")
                    if node_chroma_fill:
                        r, g, b = getattr(mask, 'fill_color', (0.18, 0.18, 0.18))
                        node_chroma_fill['color'].setValue([r, g, b, 0.0])
                else:
                    # EV
                    node_mask_ev = grp.node(f"Mask_{i+1}_EV")
                    if node_mask_ev:
                        ev = getattr(mask, 'ev_offset', 0.0)
                        node_mask_ev['red'].setValue(ev)
                        node_mask_ev['green'].setValue(ev)
                        node_mask_ev['blue'].setValue(ev)
                        
                    # TempTint
                    node_mask_temp = grp.node(f"Mask_{i+1}_TempTint")
                    if node_mask_temp:
                        temp = getattr(mask, 'temperature', 0.0)
                        tint = getattr(mask, 'tint', 0.0)
                        r_s = max(0.01, 1.0 + temp + tint)
                        g_s = max(0.01, 1.0 - tint)
                        b_s = max(0.01, 1.0 - temp)
                        l = (r_s + g_s + b_s) / 3.0
                        node_mask_temp['value'].setValue([r_s/l, g_s/l, b_s/l, 1.0])
                        
                # Blend
                node_blend = grp.node(f"Mask_{i+1}_Blend")
                if node_blend:
                    node_blend['value'].setValue(getattr(mask, 'blend', 1.0))
                    
        # 5. Update Horizon
        if getattr(st, 'horizon_enable', False):
            node_ground_mask = grp.node("HDRI_Ground_Mask")
            if node_ground_mask:
                hh = getattr(st, 'horizon_height', 0.5)
                hf = getattr(st, 'horizon_feather', 0.1)
                node_ground_mask['expr3'].setValue(f"smoothstep(-{hf}/2.0, {hf}/2.0, {hh} - y/height)")
                
            node_ground_ev = grp.node("HDRI_Ground_EV")
            if node_ground_ev:
                gev = getattr(st, 'ground_ev_offset', 0.0)
                node_ground_ev['red'].setValue(gev)
                node_ground_ev['green'].setValue(gev)
                node_ground_ev['blue'].setValue(gev)
                
            node_sky_ev = grp.node("HDRI_Sky_EV")
            if node_sky_ev:
                sev = getattr(st, 'sky_ev_offset', 0.0)
                node_sky_ev['red'].setValue(sev)
                node_sky_ev['green'].setValue(sev)
                node_sky_ev['blue'].setValue(sev)
                
            node_ground_temp = grp.node("HDRI_Ground_TempTint")
            if node_ground_temp:
                gtemp = getattr(st, 'ground_temperature', 0.0)
                gtint = getattr(st, 'ground_tint', 0.0)
                r_s = max(0.01, 1.0 + gtemp + gtint)
                g_s = max(0.01, 1.0 - gtint)
                b_s = max(0.01, 1.0 - gtemp)
                l = (r_s + g_s + b_s) / 3.0
                node_ground_temp['value'].setValue([r_s/l, g_s/l, b_s/l, 1.0])
                
            node_ground_desat = grp.node("HDRI_Ground_Desat")
            if node_ground_desat:
                node_ground_desat['saturation'].setValue(1.0 - getattr(st, 'ground_desat', 0.0))
                
            node_sky_temp = grp.node("HDRI_Sky_TempTint")
            if node_sky_temp:
                stemp = getattr(st, 'sky_temperature', 0.0)
                stint = getattr(st, 'sky_tint', 0.0)
                r_s = max(0.01, 1.0 + stemp + stint)
                g_s = max(0.01, 1.0 - stint)
                b_s = max(0.01, 1.0 - stemp)
                l = (r_s + g_s + b_s) / 3.0
                node_sky_temp['value'].setValue([r_s/l, g_s/l, b_s/l, 1.0])
                
            node_sky_desat = grp.node("HDRI_Sky_Desat")
            if node_sky_desat:
                node_sky_desat['saturation'].setValue(1.0 - getattr(st, 'sky_desat', 0.0))
                
        # 6. Update Softclip
        if getattr(st, 'softclip_enable', False):
            node_softclip = grp.node("HDRI_SoftClip")
            if node_softclip:
                node_softclip['conversion'].setValue("logarithmic")
                t = 0.18 * (2.0 ** getattr(st, 'softclip_threshold', 5.0))
                rolloff = 0.18 * (2.0 ** getattr(st, 'softclip_rolloff', 2.0))
                node_softclip['temp_expr0'].setValue(str(t))
                node_softclip['temp_expr1'].setValue(str(rolloff))

        # 7. Update Plate Adjustments (Global Nodes)
        plate_ev = nuke.toNode("Reference_Plate_EV")
        if plate_ev:
            ev = getattr(st, 'plate_ev_offset', 0.0)
            plate_ev['red'].setValue(ev)
            plate_ev['green'].setValue(ev)
            plate_ev['blue'].setValue(ev)
            
        plate_sat = nuke.toNode("Reference_Plate_Sat")
        if plate_sat:
            plate_sat['saturation'].setValue(getattr(st, 'plate_saturation', 1.0))
            
        plate_temp = nuke.toNode("Reference_Plate_TempTint")
        if plate_temp:
            temp = getattr(st, 'plate_temperature', 0.0)
            tint = getattr(st, 'plate_tint', 0.0)
            r_scale = max(0.01, 1.0 + temp + tint)
            g_scale = max(0.01, 1.0 - tint)
            b_scale = max(0.01, 1.0 - temp)
            lum = (r_scale + g_scale + b_scale) / 3.0
            plate_temp['value'].setValue([r_scale/lum, g_scale/lum, b_scale/lum, 1.0])

        # 8. Update CG Lights (in separate group)
        cg_grp = nuke.toNode("CG_Lookdev_Match")
        if cg_grp and getattr(st, 'cg_lights', None):
            any_solo = any(p.get("solo", False) for p in st.cg_light_params.values())
            
            for name in st.cg_lights.keys():
                params = st.cg_light_params.get(name, {})
                
                enabled = True
                if any_solo:
                    if not params.get("solo", False):
                        enabled = False
                else:
                    if not params.get("enabled", True):
                        enabled = False
                        
                mult_alpha = 1.0 if enabled else 0.0
                
                node_ev = cg_grp.node(f"{name}_EV")
                if node_ev:
                    ev = params.get("ev", 0.0)
                    node_ev['red'].setValue(ev)
                    node_ev['green'].setValue(ev)
                    node_ev['blue'].setValue(ev)
                    
                node_temp = cg_grp.node(f"{name}_TempTint")
                if node_temp:
                    temp = params.get("temp", 0.0)
                    tint = params.get("tint", 0.0)
                    color = params.get("color", [1.0, 1.0, 1.0])
                    
                    r_scale = max(0.01, 1.0 + temp + tint)
                    g_scale = max(0.01, 1.0 - tint)
                    b_scale = max(0.01, 1.0 - temp)
                    lum = (r_scale + g_scale + b_scale) / 3.0
                    cr, cg, cb = r_scale/lum, g_scale/lum, b_scale/lum
                    
                    fr = cr * color[0] * mult_alpha
                    fg = cg * color[1] * mult_alpha
                    fb = cb * color[2] * mult_alpha
                    
                    node_temp['value'].setValue([fr, fg, fb, 1.0])
def register_panel():
    try:
        import nuke
        import nukescripts
        
        nukescripts.panels.registerWidgetAsPanel(
            '__import__("hdri_match.nuke_panel").nuke_panel.NukeHdriPanel',
            'HDRI Match Plate',
            'com.vfx.hdrimatchplate'
        )
        
        pane_menu = nuke.menu('Pane')
        pane_menu.addCommand('HDRI Match Plate', 'nukescripts.panels.restorePanel("com.vfx.hdrimatchplate")')
        
    except ImportError:
        # Not in Nuke
        pass

if __name__ == "__main__":
    register_panel()
