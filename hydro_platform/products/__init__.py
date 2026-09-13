"""Products 输出层：年度发电量排名计算（设计文档 §20）。

计算并导出全球水电站年度发电量 Top 100。
"""

from __future__ import annotations
from typing import List, Optional
from pathlib import Path
import sqlite3
import csv
import json

from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class GenerationRanking:
    """年度发电量排名计算器

    基于 generation_records 表计算指定年份的发电量 Top N。
    筛选条件（文档 §20.1）：
    - period_type = 'calendar_year'（日历年）
    - value_type = 'actual'（实际值，非估算）
    - measurement_scope = 'plant'（全站口径）
    - review_status = 'approved'（已审核）
    - publication_status = 'publishable'（可发布）
    """

    def __init__(self, conn: sqlite3.Connection):
        """初始化排名计算器

        Args:
            conn: SQLite数据库连接
        """
        self.conn = conn

    def calculate_top_n(
        self,
        year: int,
        period_type: str = 'calendar_year',
        limit: int = 100,
        country: Optional[str] = None
    ) -> List[dict]:
        """计算指定年份 Top N（D04修复：使用统一可信过滤器）

        Args:
            year: 目标年份
            period_type: 统计口径（默认 calendar_year）
            limit: 排名数量（默认 100）
            country: 可选国家过滤（如 'CN', 'BR'）

        Returns:
            排名列表，每条包含：
            - rank: 排名
            - entity_id: 电站ID
            - canonical_name: 电站名称
            - country: 国家
            - year: 年份
            - generation_gwh: 发电量（GWh）
            - confidence_score: 置信度分数
            - evidence_id: 证据ID
        """
        from hydro_platform.products.trustworthy_filter import get_top_n_trustworthy

        # 使用统一可信过滤器
        records = get_top_n_trustworthy(
            self.conn,
            year=str(year),
            n=limit,
            country=country
        )

        # 添加排名
        for i, record in enumerate(records, start=1):
            record['rank'] = i
            record['confidence_score'] = record.pop('confidence', None)

        logger.info(f"计算 {year} 年 Top {limit}: 共 {len(records)} 条可信记录")
        return records

    def calculate_top_n_by_country(
        self,
        year: int,
        limit_per_country: int = 10
    ) -> dict[str, List[dict]]:
        """按国家分别计算 Top N

        Args:
            year: 目标年份
            limit_per_country: 每个国家的排名数量

        Returns:
            字典，键为国家代码，值为排名列表
        """
        # 查询所有国家
        countries = self.conn.execute("""
            SELECT DISTINCT s.country
            FROM generation_records r
            JOIN stations s ON r.entity_id = s.entity_id
            WHERE r.period_label = ?
            AND s.country IS NOT NULL
            ORDER BY s.country
        """, (str(year),)).fetchall()

        results = {}
        for (country,) in countries:
            country_ranking = self.calculate_top_n(
                year=year,
                limit=limit_per_country,
                country=country
            )
            if country_ranking:
                results[country] = country_ranking

        logger.info(f"按国家计算 {year} 年排名: {len(results)} 个国家")
        return results

    def get_statistics(self, year: int) -> dict:
        """获取年度统计信息

        Args:
            year: 目标年份

        Returns:
            统计信息字典：
            - total_records: 总记录数
            - total_stations: 电站数
            - total_countries: 国家数
            - total_generation_twh: 总发电量（TWh）
            - avg_generation_gwh: 平均发电量（GWh）
        """
        stats = self.conn.execute("""
            SELECT
                COUNT(*) AS total_records,
                COUNT(DISTINCT r.entity_id) AS total_stations,
                COUNT(DISTINCT s.country) AS total_countries,
                SUM(r.generation_gwh) AS total_generation_gwh,
                AVG(r.generation_gwh) AS avg_generation_gwh
            FROM generation_records r
            JOIN stations s ON r.entity_id = s.entity_id
            WHERE r.period_label = ?
            AND r.period_type = 'calendar_year'
            AND r.value_type = 'actual'
            AND r.measurement_scope = 'plant'
        """, (str(year),)).fetchone()

        result = dict(stats)
        # 转换为 TWh
        result['total_generation_twh'] = result['total_generation_gwh'] / 1000.0 if result['total_generation_gwh'] else 0

        return result

    def export_to_csv(
        self,
        year: int,
        output_path: Path,
        limit: int = 100
    ) -> None:
        """导出为 CSV 文件

        Args:
            year: 目标年份
            output_path: 输出文件路径
            limit: 排名数量
        """
        top_n = self.calculate_top_n(year, limit=limit)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'rank', 'entity_id', 'canonical_name', 'country',
                'capacity_mw', 'year', 'generation_gwh', 'unit',
                'confidence_score', 'source_id'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for record in top_n:
                writer.writerow({
                    k: record.get(k) for k in fieldnames
                })

        logger.info(f"Top {limit} 已导出到 {output_path}")

    def export_to_json(
        self,
        year: int,
        output_path: Path,
        limit: int = 100,
        include_stats: bool = True
    ) -> None:
        """导出为 JSON 文件

        Args:
            year: 目标年份
            output_path: 输出文件路径
            limit: 排名数量
            include_stats: 是否包含统计信息
        """
        top_n = self.calculate_top_n(year, limit=limit)

        output_data = {
            'year': year,
            'limit': limit,
            'count': len(top_n),
            'ranking': top_n
        }

        # 可选添加统计信息
        if include_stats:
            stats = self.get_statistics(year)
            output_data['statistics'] = stats

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Top {limit} 已导出到 {output_path}")

    def export_markdown_report(
        self,
        year: int,
        output_path: Path,
        limit: int = 100
    ) -> None:
        """导出为 Markdown 报告

        Args:
            year: 目标年份
            output_path: 输出文件路径
            limit: 排名数量
        """
        top_n = self.calculate_top_n(year, limit=limit)
        stats = self.get_statistics(year)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            # 标题
            f.write(f"# 全球水电站发电量 Top {limit} ({year})\n\n")

            # 统计摘要
            f.write("## 统计摘要\n\n")
            f.write(f"- **总记录数**: {stats['total_records']}\n")
            f.write(f"- **电站数**: {stats['total_stations']}\n")
            f.write(f"- **国家数**: {stats['total_countries']}\n")
            f.write(f"- **总发电量**: {stats['total_generation_twh']:.2f} TWh\n")
            f.write(f"- **平均发电量**: {stats['avg_generation_gwh']:.2f} GWh\n\n")

            # 排名表格
            f.write("## 排名\n\n")
            f.write("| 排名 | 电站名称 | 国家 | 容量(MW) | 发电量(GWh) | 置信度 |\n")
            f.write("|------|---------|------|----------|-------------|--------|\n")

            for record in top_n:
                rank = record['rank']
                name = record['canonical_name']
                country = record['country'] or 'N/A'
                capacity = f"{record['capacity_mw']:.0f}" if record.get('capacity_mw') else 'N/A'
                generation = f"{record['generation_gwh']:.2f}"
                confidence = f"{record.get('confidence_score') or 0:.2f}"

                f.write(f"| {rank} | {name} | {country} | {capacity} | {generation} | {confidence} |\n")

        logger.info(f"Markdown报告已导出到 {output_path}")


class RankingConfig:
    """排名计算配置"""

    @staticmethod
    def get_default_limit() -> int:
        """获取默认排名数量

        Returns:
            默认 100
        """
        return 100

    @staticmethod
    def get_supported_period_types() -> List[str]:
        """获取支持的统计口径

        Returns:
            支持的 period_type 列表
        """
        return ['calendar_year', 'water_year', 'fiscal_year']

    @staticmethod
    def get_default_output_dir() -> Path:
        """获取默认输出目录

        Returns:
            默认输出目录路径
        """
        return Path('outputs/rankings')
