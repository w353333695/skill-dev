"""Hub 只保留成品和商品索引的目录回归。"""
from pathlib import Path
import unittest


class HubProductsTests(unittest.TestCase):
    def test_only_products_and_index_remain(self):
        hub = Path(__file__).resolve().parents[2] / 'hub'
        for path in hub.rglob('*'):
            with self.subTest(path=path.relative_to(hub)):
                self.assertNotIn(path.name, ('tests', '__pycache__'))
                if path.is_file():
                    self.assertTrue(
                        path.name == '.gitkeep' or path == hub / 'INDEX.yaml'
                        or path.suffix in ('.zip', '.gz', '.xlsx'),
                        'Hub 不得存放开发材料: %s' % path)


if __name__ == '__main__':
    unittest.main()
