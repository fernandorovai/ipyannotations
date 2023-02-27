from math import pi
from typing import List, Optional

import ipywidgets as widgets
from ipycanvas import hold_canvas
from traitlets import Bool, observe

from .abstract_canvas import AbstractAnnotationCanvas
from .color_utils import hex_to_rgb, rgba_to_html_string
from .image_utils import dist, only_inside_image, trigger_redraw
from .shapes import BoundingBox
from ipywidgets import Image
import os

class BoundingBoxAnnotationCanvas(AbstractAnnotationCanvas):

    editing = Bool(default_value=False)
    annotations: List[BoundingBox]
    _proposed_annotation: Optional[BoundingBox] = None

    debug_output = widgets.Output()
    prev_xy = None
    draggingCorner = None
    draggingBox = None
    boxActive = -1
    adding = False

    # print(dir(editing))
    @observe("point_size", "editing")
    def re_draw(self, change_details=None):  # noqa: D001
        with hold_canvas(self):
            self.annotation_canvas.clear()
            # draw all existing polygons:
            for idx, annotation in enumerate(self.annotations):
                self.draw_box(annotation, idx)
            # draw the current box:
            if self._proposed_annotation is not None:
                self.draw_box(self._proposed_annotation, proposed=True)


    def draw_box(self, box: BoundingBox, idx=None, proposed: bool = False, label=True):
        """Draw a box onto the canvas.

        Parameters
        ----------
        box : BoundingBox
            The box to draw.
        proposed : bool, optional
            Whether this box is a proposal, by default False
        """

        color = self.colormap.get(box.label, "#000000")
        canvas = self[1]
        rgb = hex_to_rgb(color)

        canvas.line_width = 3
        canvas.stroke_style = rgba_to_html_string(rgb + (1.0,))
        canvas.set_line_dash([10, 5] if proposed else [])
        canvas.fill_style = rgba_to_html_string(rgb + (self.opacity,))
        corners = [self.image_to_canvas_coordinates(corner) for corner in box.corners]
        canvas.begin_path()
        canvas.move_to(*corners[0])
        for corner in corners[1:]:
            canvas.line_to(*corner)
        canvas.close_path()
        canvas.stroke()

        x0, y0, x1, y1 = box.xyxy
        x0, y0 = self.image_to_canvas_coordinates((x0, y0))
        x1, y1 = self.image_to_canvas_coordinates((x1, y1))
        
        titleBarSize = (abs(x1-x0), 10)
        deleteBtnSize = (15,15)

        # if not self.editing:
        #     xMin = min(x0,x1)
        #     yMin = min(y0,y1)

        #     canvas.fill_rect(xMin,yMin-titleBarSize[1], width=titleBarSize[0], height=titleBarSize[1])
        #     canvas.fill_style = "black"
        #     canvas.font = "14px serif"
        #     canvas.fill_text(box.label, min(x0,x1), yMin)

        # if self.editing:
        if self.boxActive == idx:
            canvas.fill_style = rgba_to_html_string(rgb + (1.0,))
            canvas.fill_arcs([x0, x0, x1, x1], [y0, y1, y0, y1], self.point_size, 0, 2 * pi)
            
            if label:
                titleBarSize = (abs(x1-x0), 10)
                deleteBtnSize = (15,15)

                xMin = min(x0,x1)
                yMin = min(y0,y1)

                canvas.fill_rect(xMin + self.point_size,yMin-titleBarSize[1], width=titleBarSize[0] - 2*self.point_size, height=titleBarSize[1])
                canvas.fill_style = "black"
                canvas.font = "14px serif"
                canvas.fill_text(box.label, min(x0,x1) + self.point_size, yMin)
        else:        
            xMin = min(x0,x1)
            yMin = min(y0,y1)

            canvas.fill_rect(xMin,yMin-titleBarSize[1], width=titleBarSize[0], height=titleBarSize[1])
            canvas.fill_style = "black"
            canvas.font = "14px serif"
            canvas.fill_text(box.label, min(x0,x1), yMin)

    @trigger_redraw
    @only_inside_image
    def on_click(self, x: float, y: float):
        """Handle a click.

        This function either starts a new proposed box and sets the
        dragging functionality, or in editing mode sets dragging one of
        the corners.

        Parameters
        ----------
        x : float
            The x coordinate, relative to the image.
        y : float
            The y coordinate, relative to the image.
        """
        # if not self.editing:
        if self.adding:
            x, y = int(x), int(y)
            self._proposed_annotation = BoundingBox((x, y, x, y), label=self.current_class)

            def drag_func(x, y):
                if self._proposed_annotation is not None:
                    self._proposed_annotation.move_corner(2, x, y)
            self.draggingCorner = drag_func
        else:
            for idx, box in enumerate(self.annotations):
                # if dist(box.center, (x, y)) < (box.size[0]//2) - self.point_size:
                # if x > x0 + self.point_size and x < x1 - self.point_size and y > y0 + self.point_size and y < y1 - self.point_size:
                if dist(box.center, (x, y)) <= abs(max(box.size)//2): #this thresh is not correct, depending on the ratio, it'll move even if the pointer is not within the box
                    self.boxActive = idx
                    self.draggingBox = lambda x,y,prev_xy: box.move_box(x,y, prev_xy)
                    return
                
                # see if the x / y is near any points
                for index, point in enumerate(box.corners):
                    if dist(point, (x, y)) < self.point_size:
                        self.boxActive = idx
                        self.draggingCorner = lambda x, y: box.move_corner(index, x, y)
                        
                        def undo_move_corner():
                            box.move_corner(index, *point)
                            self.re_draw()

                        self._undo_queue.append(undo_move_corner)
                        return
        self.boxActive = -1
        self.adding = False

    @trigger_redraw
    def on_key_down(self, key, shift_key, ctrl_key, meta_key):
        filteredAnnotations = []
        self.adding = False
        annotationsBkp = list(self.annotations)

        if shift_key:
            self.adding = True

        if self.boxActive > -1:
            if key == 'Delete':
                for idx, annotation in enumerate(self.annotations):
                    if self.boxActive != idx:
                        filteredAnnotations.append(annotation)
                self.annotations = filteredAnnotations

                def undo_delete():
                    self.annotations = annotationsBkp
                    self.re_draw()
                self._undo_queue.append(undo_delete)                  

            elif key == 'c':
                oldBoxCls = self.annotations[self.boxActive].label
                self.annotations[self.boxActive].set_label(self.current_class)

                def undo_relabel():
                    self.annotations[self.boxActive].set_label(oldBoxCls)
                    self.re_draw()
                self._undo_queue.append(undo_relabel)

    @trigger_redraw
    @only_inside_image
    def on_drag(self, x: float, y: float):
        """Handle a dragging action.

        Parameters
        ----------
        x : float
            The new x coordinate, relative to the image.
        y : float
            The new y coordinate, relative to the image.
        """
     
        if self.draggingBox is not None:
            self.draggingBox(int(x), int(y), self.prev_xy)

        if self.draggingCorner is not None:
            self.draggingCorner(int(x), int(y))

        self.prev_xy = [x,y]


    @trigger_redraw
    def on_release(self, x: float, y: float):
        """Handle a mouse release.

        This function will re-set the dragging handler, and append a new
        box to the annotation data if required.

        Parameters
        ----------
        x : float
        y : float
        """

        self.draggingBox = None
        self.draggingCorner = None

        if self._proposed_annotation is not None:
            x0, y0, x1, y1 = self._proposed_annotation.xyxy

            if not (x0 == x1 and y0 == y1):
                self.annotations.append(self._proposed_annotation)
                self._undo_queue.append(self._undo_new_box)

            self._proposed_annotation = None

    @trigger_redraw
    def _undo_new_box(self):
        self.annotations.pop()

    def init_empty_data(self):
        self.annotations: List[BoundingBox] = []
        self._undo_queue.clear()

    @property
    def data(self):
        """
        The annotation data, as List[ Dict ].

        The format is a list of dictionaries, with the following key / value
        combinations:

        +------------------+-------------------------------+
        |``'type'``        | ``'box'``                     |
        +------------------+-------------------------------+
        |``'label'``       | ``<class label>``             |
        +------------------+-------------------------------+
        |``'xyxy'``        | ``<tuple of x0, y0, x1, y1>`` |
        +------------------+-------------------------------+
        """

        return [annotation.data for annotation in self.annotations]

    @data.setter  # type: ignore
    @trigger_redraw
    def data(self, value: List[dict]):
        """Set the annotation data on this canvas.

        Parameters
        ----------
        value : List[dict]
            List of dictionaries, with keys `type`, `label`, and `xyxy`.
        """
        self.init_empty_data()
        self.annotations = [BoundingBox.from_data(annotation.copy()) for annotation in value]
