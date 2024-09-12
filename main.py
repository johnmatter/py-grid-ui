#!/usr/bin/env python3.11
from abc import ABC, abstractmethod
import asyncio
import signal
import monome
from enum import Enum
import time
import random
import string
import copy
from collections import deque
import pdb

def generate_unique_id(existing_ids, length=6):
    while True:
        new_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if new_id not in existing_ids:
            return new_id

"""
      .-.                      
      : :                      
 .--. : `-.  .--.  .---.  .--. 
`._-.': .. :' .; ; : .; `' '_.'
`.__.':_;:_;`.__,_;: ._.'`.__.'
                   : :         
                   :_; 
"""
class Shape(ABC):
    def __init__(self, points):
        self.points = points

    @abstractmethod
    def contains_point(self, x, y):
        pass

    @abstractmethod
    def draw(self, buffer, brightness):
        pass

class Point(Shape):
    def contains_point(self, x, y):
        return (x, y) == self.points[0]

    def draw(self, buffer, brightness):
        x, y = self.points[0]
        buffer.led_level_set(x, y, brightness)

class Rectangle(Shape):
    def contains_point(self, x, y):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        return min_x <= x <= max_x and min_y <= y <= max_y

    def draw(self, buffer, brightness):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        # Ensure we draw from the minimum to maximum coordinates
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                buffer.led_level_set(x, y, brightness)

class Triangle(Shape):
    def contains_point(self, x, y):
        if len(self.points) < 3:
            return False
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        b1 = sign((x, y), self.points[0], self.points[1]) < 0
        b2 = sign((x, y), self.points[1], self.points[2]) < 0
        b3 = sign((x, y), self.points[2], self.points[0]) < 0
        return (b1 == b2) and (b2 == b3)

    def draw(self, buffer, brightness):
        if len(self.points) < 3:
            print(f"Warning: Triangle has insufficient points: {self.points}")
            return
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        min_x, max_x = min(x1, x2, x3), max(x1, x2, x3)
        min_y, max_y = min(y1, y2, y3), max(y1, y2, y3)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                if self.contains_point(x, y):
                    buffer.led_level_set(x, y, brightness)

"""
       _ 
      :_;
.-..-..-.
: :; :: :
`.__.':_;
"""
class UIElementType(Enum):
    TRIGGER = 1
    TOGGLE = 2
    SLIDER = 3

class UIElement:
    def __init__(self, id, shape):
        self.id = id
        self.shape = shape
        self.state = 0
        self.flash_start = 0
        self.base_brightness = 3
        self.peak_brightness = 10

    def contains_point(self, x, y):
        return self.shape.contains_point(x, y)

    def touch(self, x, y, s):
        self.flash_start = time.time()
        print(f"{self.id} {s}")

    def get_brightness(self):
        return self.base_brightness if self.state == 0 else self.peak_brightness

    def clip_brightness(self):
        self.base_brightness = max(0, min(self.base_brightness, 13))
        self.peak_brightness = max(2, min(self.peak_brightness, 15))

    def adjust_brightness(self, delta):
        self.base_brightness += delta
        self.peak_brightness += delta
        self.clip_brightness()

    def draw(self, buffer):
        raise NotImplementedError("Subclasses should implement this!")

class Toggle(UIElement):
    # def get_brightness(self):
    #     elapsed = time.time() - self.flash_start
    #     if self.state:  # If the toggle is on
    #         if elapsed < 0.5:  # Growing phase
    #             return int(self.base_brightness + (self.peak_brightness - self.base_brightness) * (elapsed / 0.5))
    #         else:
    #             return self.peak_brightness  # Max brightness after growing
    #     else:  # If the toggle is off
    #         if elapsed < 0.5:  # Fading out phase
    #             return int(self.peak_brightness * (1 - (elapsed / 0.5)))
    #         else:
    #             return self.base_brightness  # Return to base brightness when fully faded out

    def touch(self, x, y, s):
        super().touch(x,y,s)
        self.state = s

    def draw(self, buffer):
        self.shape.draw(
            buffer,
            self.get_brightness()
        )

class Trigger(UIElement):
    def touch(self, x, y, s):
        super().touch(x,y,s)
        if s == 1:
            self.state = 1 - self.state

    def draw(self, buffer):
        self.shape.draw(
            buffer,
            self.get_brightness()
        )

class Slider(UIElement):
    def draw(self, buffer):
        # Slider logic: draw a line or a series of points based on the current value
        # For example, we can represent the slider's value with a line of LEDs
        for i in range(self.shape.points[0][0], self.shape.points[1][0] + 1):
            brightness = self.base_brightness if self.state == 0 else self.peak_brightness
            buffer.led_level_set(i, self.shape.points[0][1], brightness)

"""
            _    .-.
           :_;   : :
 .--. .--. .-. .-' :
' .; :: ..': :' .; :
`._. ;:_;  :_;`.__.'
 .-. :              
 `._.'
"""
class GridUI(monome.GridApp):
    def __init__(self):
        super().__init__()
        self.width = 0
        self.height = 0
        self.connected = False
        self.is_running = False
        self.update_task = None
        self.meta_pressed = False
        self.selected_element = None
        self.delete_press_time = 0
        self.delete_press_count = 0
        self.paste_buffer = None
        self.meta_history = deque(maxlen=5)  # Store last 5 button presses
        self.ui_elements = {}
        self.current_points = []
        self.reset()

    def reset(self):
        self.ui_elements.clear()
        self.current_points.clear()
        self.meta_pressed = False
        self.selected_element = None
        self.delete_press_time = 0
        self.delete_press_count = 0
        self.meta_history.clear()
        # We don't reset paste_buffer here to keep it across resets

    def on_grid_ready(self):
        self.width = self.grid.width
        self.height = self.grid.height
        self.connected = True
        print(f"Grid connected: {self.width}x{self.height}")
        self.reset()
        self.start_update_loop()
        self.draw()

    def start_update_loop(self):
        if not self.is_running:
            self.is_running = True
            self.update_task = asyncio.create_task(self.update_loop())

    async def update_loop(self):
        while self.is_running:
            self.draw()
            await asyncio.sleep(0.1)  # Update every 100ms

    def stop_update_loop(self):
        self.is_running = False
        if self.update_task:
            self.update_task.cancel()

    def cleanup(self):
        self.stop_update_loop()
        if self.connected:
            buffer = monome.GridBuffer(self.width, self.height)
            buffer.render(self.grid)
        print("\nCleaning up and exiting...")

    def on_grid_key(self, x, y, s):
        if not self.connected:
            return

        if x == 0 and y == self.height - 1:  # Meta key
            self.meta_pressed = (s == 1)
            if not self.meta_pressed:
                self.create_ui_element()
                self.selected_element = None
                self.current_points.clear()
            self.draw()
            return

        if self.meta_pressed:
            self.handle_meta_interaction(x, y, s)
        else:
            self.handle_normal_interaction(x, y, s)

        self.draw()

    def handle_normal_interaction(self, x, y, s):
        if y == self.height - 1:  # Ignore bottom row
            return

        print(f"{x:02d} {y:02d} {s}")

        # Check if the point is inside any UI element
        for element_id, element in self.ui_elements.items():
            if element.contains_point(x, y):
                print(f'touched {element_id}')
                element.touch(x, y, s)
                break

    def handle_meta_interaction(self, x, y, s):
        if s == 1:  # Key pressed
            self.meta_history.append((x, y))
            print(f"Meta interaction: x={x}, y={y}")
            
            if y < self.height - 1:  # Exclude bottom row for UI element creation
                if (x, y) not in self.current_points:
                    self.current_points.append((x, y))
                    print(f"Added point: {(x, y)}. Current points: {self.current_points}")
            
            if self.selected_element:
                meta_ui_pos = self.get_meta_ui_position(self.selected_element)
                if (x, y) == meta_ui_pos:
                    self.selected_element.adjust_brightness(1)
                    return
                elif (x, y) == (meta_ui_pos[0] + 1, meta_ui_pos[1]):
                    self.selected_element.adjust_brightness(-1)
                    return
                elif (x, y) == (1, self.height - 1):  # Copy/Delete button
                    current_time = time.time()
                    if current_time - self.delete_press_time < 0.5:  # Double press within 0.5 seconds
                        self.delete_selected_element()
                        return
                    else:
                        self.copy_selected_element()
                    self.delete_press_time = current_time
                    return

            # If we didn't press a meta UI button, check for polygon selection or pasting
            if y < self.height - 1:  # Exclude bottom row
                element_at_position = self.get_element_at_position(x, y)
                if element_at_position:
                    if self.selected_element and self.selected_element != element_at_position:
                        self.deselect_element(self.selected_element)
                    self.selected_element = element_at_position
                    self.delete_press_count = 0  # Reset delete press count when selecting a new element
                elif self.paste_buffer and self.last_pressed_was_copy_delete():
                    self.paste_element(x, y)
                else:
                    if self.selected_element:
                        self.deselect_element(self.selected_element)
                        self.selected_element = None

    def deselect_element(self, element):
        element.reset_brightness()
        element.state = 0  # Reset the state of the element

    def create_ui_element(self):
        new_id = generate_unique_id(self.ui_elements.keys())
        if len(self.current_points) == 2:
            new_element = Trigger(new_id, Rectangle(self.current_points.copy()))
        elif len(self.current_points) == 3:
            new_element = Trigger(new_id, Triangle(self.current_points.copy()))
        elif len(self.current_points) == 1:
            new_element = Trigger(new_id, Point(self.current_points.copy()))
        else:
            print(f"Warning: Invalid number of points for UI element creation: {len(self.current_points)}")
            return

        if new_element and not self.element_in_bottom_row(new_element) and not self.elements_overlap(new_element):
            self.ui_elements[new_id] = new_element
            print(f"Created new {type(new_element).__name__} {new_element.id}")
            self.current_points.clear()  # Clear points after creating the element
        else:
            print("Cannot create UI element: it would be in the bottom row or overlap with existing elements")

    def elements_overlap(self, new_element):
        for existing_element in self.ui_elements.values():
            if self.check_overlap(new_element, existing_element):
                return True
        return False

    def check_overlap(self, elem1, elem2):
        # Check if any point of elem1 is inside elem2 or vice versa
        for point in elem1.shape.points:
            if elem2.contains_point(point[0], point[1]):
                return True
        for point in elem2.shape.points:
            if elem1.contains_point(point[0], point[1]):
                return True

        # Check if any edges intersect
        edges1 = self.get_edges(elem1.shape.points)
        edges2 = self.get_edges(elem2.shape.points)
        for edge1 in edges1:
            for edge2 in edges2:
                if self.lines_intersect(edge1, edge2):
                    return True

        return False

    def get_edges(self, points):
        edges = []
        for i in range(len(points)):
            edges.append((points[i], points[(i + 1) % len(points)]))
        return edges

    def lines_intersect(self, line1, line2):
        x1, y1 = line1[0]
        x2, y2 = line1[1]
        x3, y3 = line2[0]
        x4, y4 = line2[1]

        def ccw(A, B, C):
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

        return ccw((x1, y1), (x3, y3), (x4, y4)) != ccw((x2, y2), (x3, y3), (x4, y4)) and \
               ccw((x1, y1), (x2, y2), (x3, y3)) != ccw((x1, y1), (x2, y2), (x4, y4))

    def last_pressed_was_copy_delete(self):
        return len(self.meta_history) >= 2 and self.meta_history[-2] == (1, self.height - 1)

    def copy_selected_element(self):
        if self.selected_element:
            self.paste_buffer = copy.deepcopy(self.selected_element)
            print("Element copied to paste buffer")

    def delete_selected_element(self):
        if self.selected_element:
            element_to_delete = None
            for element_id, element in self.ui_elements.items():
                if element == self.selected_element:
                    element_to_delete = element_id
                    break
            if element_to_delete:
                del self.ui_elements[element_to_delete]
            self.selected_element = None
            print("Element deleted")

    def paste_element(self, x, y):
        if not self.paste_buffer:
            return

        new_element = copy.deepcopy(self.paste_buffer)
        
        # Calculate the offset to move the element
        old_x, old_y = new_element.shape.points[0]
        offset_x, offset_y = x - old_x, y - old_y

        # Move the element
        new_element.shape.points = [(p[0] + offset_x, p[1] + offset_y) for p in new_element.shape.points]

        # Check if the new element would be in the bottom row or overlap with existing elements
        if self.element_in_bottom_row(new_element) or self.elements_overlap(new_element):
            print("Cannot paste: element would be in bottom row or overlap with existing elements")
            return

        new_id = generate_unique_id(self.ui_elements.keys())
        self.ui_elements[new_id] = new_element
        self.selected_element = new_element
        print("Element pasted")

    def element_in_bottom_row(self, element):
        return any(point[1] == self.height - 1 for point in element.shape.points)

    def get_element_at_position(self, x, y):
        for element in self.ui_elements.values():
            if element.contains_point(x, y):
                return element
        return None

    def get_meta_ui_position(self, element):
        # Find the rightmost point of the element
        max_x = max(point[0] for point in element.shape.points)
        min_y = min(point[1] for point in element.shape.points)

        # Position the meta UI to the right of the element
        meta_x = max_x + 1
        meta_y = min_y

        # If the meta UI would be off the grid, move it left
        if meta_x >= self.width - 1:
            meta_x = max_x - 2

        # Ensure the meta UI is fully on the grid
        meta_x = max(0, min(self.width - 2, meta_x))
        meta_y = max(0, min(self.height - 1, meta_y))

        return (meta_x, meta_y)

    def draw(self):
        if not self.connected:
            return
        
        buffer = monome.GridBuffer(self.width, self.height)

        # Draw UI elements
        for element in self.ui_elements.values():
            element.draw(buffer)

        # Draw current selection
        for point in self.current_points:
            buffer.led_level_set(point[0], point[1], 15)

        # Draw meta key
        buffer.led_level_set(0, self.height - 1, 15 if self.meta_pressed else 5)

        # Draw meta UI if an element is selected
        if self.meta_pressed and self.selected_element:
            meta_ui_pos = self.get_meta_ui_position(self.selected_element)
            buffer.led_level_set(meta_ui_pos[0], meta_ui_pos[1], 15)  # Increment brightness
            buffer.led_level_set(meta_ui_pos[0] + 1, meta_ui_pos[1], 15)  # Decrement brightness
            
            # Draw copy/delete button
            copy_delete_brightness = 15 if self.paste_buffer else 8
            buffer.led_level_set(1, self.height - 1, copy_delete_brightness)

        buffer.render(self.grid)

"""
                 _       
                :_;      
,-.,-.,-. .--.  .-.,-.,-.
: ,. ,. :' .; ; : :: ,. :
:_;:_;:_;`.__,_;:_;:_;:_;
"""
async def main():
    """
    Callback function for when a serialosc device is added.
    Arguments:
        id (str): The device ID
        type (str): The device type
        port (int): The port number for the device
    Returns: None
    """
    def serialosc_device_added(id, type, port):
        print(f'connecting to {id} ({type}) on port {port}')
        asyncio.ensure_future(grid_studies.grid.connect('127.0.0.1', port))

    """
    Handles the SIGINT signal (Ctrl+C) to gracefully exit the program.
    Arguments: signum (int) - The signal number
               frame (frame object) - Current stack frame
    Returns: None
    """
    def signal_handler(signum, frame):
        print("\nCtrl+C pressed. Cleaning up...")
        grid_studies.cleanup()
        loop.stop()

    loop = asyncio.get_running_loop()
    grid_studies = GridUI()

    serialosc = monome.SerialOsc()
    serialosc.device_added_event.add_handler(serialosc_device_added)

    await serialosc.connect()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        await loop.create_future()
    finally:
        grid_studies.cleanup()

    await loop.create_future()

if __name__ == '__main__':
    asyncio.run(main())
