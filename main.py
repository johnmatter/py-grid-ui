#!/usr/bin/env python3.11
from abc import ABC, abstractmethod
import asyncio
import signal
import monome
from enum import Enum
import time
import random
import string

def generate_unique_id(existing_ids, length=6):
    while True:
        new_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if new_id not in existing_ids:
            return new_id

class UIElementType(Enum):
    TRIGGER = 1
    TOGGLE = 2
    SLIDER = 3

class Shape(ABC):
    def __init__(self, points):
        self.points = points

    @abstractmethod
    def contains_point(self, x, y):
        pass

    @abstractmethod
    def draw(self, buffer, brightness):
        pass

class Rectangle(Shape):
    def contains_point(self, x, y):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        return x1 <= x <= x2 and y1 <= y <= y2

    def draw(self, buffer, brightness):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                buffer.led_level_set(x, y, brightness)

class Triangle(Shape):
    def contains_point(self, x, y):
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        b1 = sign((x, y), self.points[0], self.points[1]) < 0
        b2 = sign((x, y), self.points[1], self.points[2]) < 0
        b3 = sign((x, y), self.points[2], self.points[0]) < 0
        return (b1 == b2) and (b2 == b3)

    def draw(self, buffer, brightness):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        min_x, max_x = min(x1, x2, x3), max(x1, x2, x3)
        min_y, max_y = min(y1, y2, y3), max(y1, y2, y3)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                if self.contains_point(x, y):
                    buffer.led_level_set(x, y, brightness)

class UIElement:
    def __init__(self, shape, type):
        self.shape = shape
        self.type = type
        self.state = 0
        self.flash_start = 0

    def contains_point(self, x, y):
        return self.shape.contains_point(x, y)

    def draw(self, buffer):
        self.shape.draw(buffer, self.get_brightness())

    def toggle(self):
        if self.type == UIElementType.TRIGGER:
            self.state = 1
        elif self.type == UIElementType.TOGGLE:
            self.state = 1 - self.state
        elif self.type == UIElementType.SLIDER:
            # Implement slider logic here
            pass
        self.flash_start = time.time()

    def get_brightness(self):
        # Init default low level brightness
        base_brightness = 3
        brightness = base_brightness

        if self.state:
            elapsed = time.time() - self.flash_start
            if elapsed < 0.4:  # Flash for 0.4 seconds
                flash_brightness = int(15 - (elapsed / 0.1) * 4)  # Flash through 4 brightness levels
                brightness = max(base_brightness, min(15, flash_brightness))
            else:
                return 3 if self.type == UIElementType.TOGGLE else base_brightness
        return brightness

class GridStudies(monome.GridApp):
    def __init__(self):
        super().__init__()
        self.width = 0
        self.height = 0
        self.connected = False
        self.reset()
        self.is_running = False
        self.update_task = None

    def reset(self):
        self.ui_elements = {}
        self.current_points = []

    def on_grid_ready(self):
        self.width = self.grid.width
        self.height = self.grid.height
        self.connected = True
        print(f"Grid connected: {self.width}x{self.height}")
        self.reset()
        self.start_update_loop()

    def on_grid_disconnect(self):
        self.connected = False
        print("Grid disconnected")
        self.stop_update_loop()
        self.reset()

    def start_update_loop(self):
        if not self.is_running:
            self.is_running = True
            self.update_task = asyncio.create_task(self.update_loop())

    def stop_update_loop(self):
        self.is_running = False
        if self.update_task:
            self.update_task.cancel()

    async def update_loop(self):
        while self.is_running:
            self.draw()
            await asyncio.sleep(1/30)

    def create_ui_element(self, create_func):
        new_element = create_func()
        if new_element and not self.elements_overlap(new_element):
            new_id = generate_unique_id(self.ui_elements.keys())
            self.ui_elements[new_id] = new_element
        else:
            print("Cannot create overlapping UI element")

    def create_rectangle(self):
        x1, y1 = self.current_points[0]
        x2, y2 = self.current_points[1]
        points = [(min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
        return UIElement(Rectangle(points), UIElementType.TRIGGER)

    def create_triangle(self):
        return UIElement(Triangle(self.current_points), UIElementType.TOGGLE)

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

    def on_grid_key(self, x, y, s):
        if s == 1:  # Key pressed
            self.current_points.append((x, y))
        else:  # Key released
            if len(self.current_points) == 2:
                self.create_ui_element(self.create_rectangle)
            elif len(self.current_points) == 3:
                self.create_ui_element(self.create_triangle)
            else:
                # Check if the point is inside any UI element
                for element_id, element in self.ui_elements.items():
                    if element.contains_point(x, y):
                        element.toggle()
                        break
            self.current_points = []
        self.draw()

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

        buffer.render(self.grid)

    def cleanup(self):
        self.stop_update_loop()
        if self.connected:
            buffer = monome.GridBuffer(self.width, self.height)
            buffer.render(self.grid)
        print("\nCleaning up and exiting...")

"""
Main asynchronous function to set up and run the application.
Arguments: None
Returns: None
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
    grid_studies = GridStudies()

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
