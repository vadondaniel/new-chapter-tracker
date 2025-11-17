import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_dummy_browser_stack():
    if "selenium" in sys.modules:
        return
    selenium = types.ModuleType("selenium")
    webdriver_module = types.ModuleType("selenium.webdriver")
    chrome_module = types.ModuleType("selenium.webdriver.chrome")
    service_module = types.ModuleType("selenium.webdriver.chrome.service")
    options_module = types.ModuleType("selenium.webdriver.chrome.options")

    class DummyDriver:
        def __init__(self, *args, **kwargs):
            pass

        def quit(self):
            pass

    class DummyChromeService:
        def __init__(self, *args, **kwargs):
            pass

    class DummyOptions:
        def __init__(self):
            self.arguments = []

        def add_argument(self, value):
            self.arguments.append(value)

    webdriver_module.Chrome = DummyDriver
    service_module.Service = DummyChromeService
    options_module.Options = DummyOptions

    chrome_module.service = service_module
    chrome_module.options = options_module
    webdriver_module.chrome = chrome_module
    selenium.webdriver = webdriver_module

    sys.modules["selenium"] = selenium
    sys.modules["selenium.webdriver"] = webdriver_module
    sys.modules["selenium.webdriver.chrome"] = chrome_module
    sys.modules["selenium.webdriver.chrome.service"] = service_module
    sys.modules["selenium.webdriver.chrome.options"] = options_module

    webdriver_manager = types.ModuleType("webdriver_manager")
    chrome_manager = types.ModuleType("webdriver_manager.chrome")

    class DummyChromeDriverManager:
        def install(self):
            return "/tmp/chromedriver"

    chrome_manager.ChromeDriverManager = DummyChromeDriverManager
    webdriver_manager.chrome = chrome_manager
    sys.modules["webdriver_manager"] = webdriver_manager
    sys.modules["webdriver_manager.chrome"] = chrome_manager


_ensure_dummy_browser_stack()
