#!/usr/bin/env python3
"""
Inventory AI Prototype
Part of the AI Business Manager vision.
Detects stock risks, demand changes, and financial inefficiencies.
"""

import pandas as pd
import numpy as np
from io import StringIO
from typing import Dict, List, Tuple

# ------------------------------------------------------------
# 1. SAMPLE DATA (if you don't have a CSV file yet)
# ------------------------------------------------------------
SAMPLE_CSV = """product_name,current_stock,selling_price,cost_per_unit,supplier_lead_time_days,daily_sales
Coffee Beans,45,12.50,6.00,5,"30,28,32,29,27,31,30,33,28,25"
Green Tea,120,8.00,3.50,4,"15,14,16,15,13,14,12,11,10,9"
Bottled Water,500,1.20,0.60,3,"50,55,48,52,60,58,55,62,65,70"
Protein Bars,30,4.50,2.00,6,"8,7,9,6,5,4,3,2,2,1"
Hand Sanitiser,200,5.00,2.50,7,"20,22,18,15,12,10,8,6,4,3"
"""

# ------------------------------------------------------------
# 2. CORE INVENTORY AI CLASS
# ------------------------------------------------------------
class InventoryAI:
    def __init__(self, df: pd.DataFrame):
        """
        :param df: DataFrame with columns:
            product_name, current_stock, selling_price, cost_per_unit,
            supplier_lead_time_days, daily_sales (string of comma-separated ints)
        """
        self.df = df.copy()
        self._parse_sales()
        self._compute_metrics()
        self.alerts = []
        self.recommendations = []

    def _parse_sales(self):
        """Convert daily_sales strings into lists of integers."""
        self.df['sales_history'] = self.df['daily_sales'].apply(
            lambda x: [int(v) for v in x.split(',')]
        )
        # Compute average daily demand (last 7 days if available, else all)
        self.df['avg_daily_demand'] = self.df['sales_history'].apply(
            lambda hist: np.mean(hist[-7:]) if len(hist) >= 7 else np.mean(hist)
        )
        # Detect trend (simple linear regression slope on last 10 days)
        def trend(hist):
            if len(hist) < 3:
                return 0
            x = np.arange(len(hist))
            slope = np.polyfit(x, hist, 1)[0]
            return slope
        self.df['demand_trend'] = self.df['sales_history'].apply(trend)

    def _compute_metrics(self):
        """Calculate derived metrics."""
        self.df['days_of_stock'] = self.df.apply(
            lambda row: row['current_stock'] / row['avg_daily_demand'] if row['avg_daily_demand'] > 0 else np.inf,
            axis=1
        )
        self.df['reorder_point'] = self.df.apply(
            lambda row: row['avg_daily_demand'] * (row['supplier_lead_time_days'] + 2),  # +2 safety buffer
            axis=1
        )
        self.df['stock_value'] = self.df['current_stock'] * self.df['cost_per_unit']
        self.df['profit_margin'] = (self.df['selling_price'] - self.df['cost_per_unit']) / self.df['selling_price'] * 100
        # Identify dead stock: no sales in last 10 days? (if sales_history has zeros)
        self.df['is_dead'] = self.df['sales_history'].apply(lambda h: all(v == 0 for v in h[-10:]))

    def run_analysis(self):
        """Run all detection and build alert list."""
        self._detect_low_stock()
        self._detect_overstock()
        self._detect_trends()
        self._detect_financial_issues()
        self._generate_recommendations()
        return self.alerts, self.recommendations

    def _detect_low_stock(self):
        for idx, row in self.df.iterrows():
            if row['current_stock'] < row['reorder_point']:
                need = int(row['reorder_point'] * 1.5)  # order to cover lead time + safety
                self.alerts.append({
                    'priority': 'HIGH',
                    'product': row['product_name'],
                    'message': (f"Stock may run out in {row['days_of_stock']:.1f} days. "
                                f"Current: {row['current_stock']}, "
                                f"Reorder point: {row['reorder_point']:.0f}."),
                    'action': f"Order {need - row['current_stock']} units."
                })

    def _detect_overstock(self):
        # Overstock if > 90 days of demand
        for idx, row in self.df.iterrows():
            if row['days_of_stock'] > 90 and row['avg_daily_demand'] > 0:
                self.alerts.append({
                    'priority': 'MEDIUM',
                    'product': row['product_name'],
                    'message': (f"Overstocked: {row['days_of_stock']:.0f} days of stock. "
                                f"Money tied up: R{row['stock_value']:.2f}."),
                    'action': "Consider promotions or bundling to reduce surplus."
                })

    def _detect_trends(self):
        for idx, row in self.df.iterrows():
            if row['demand_trend'] < -0.5:
                self.alerts.append({
                    'priority': 'MEDIUM',
                    'product': row['product_name'],
                    'message': f"Demand is declining (trend: {row['demand_trend']:.2f} units/day).",
                    'action': "Investigate cause (e.g., competitor, seasonality)."
                })
            elif row['demand_trend'] > 0.5:
                self.alerts.append({
                    'priority': 'LOW',
                    'product': row['product_name'],
                    'message': f"Demand is increasing (trend: {row['demand_trend']:.2f} units/day).",
                    'action': "Consider increasing stock levels."
                })

    def _detect_financial_issues(self):
        # Low profit margin (< 20%)
        for idx, row in self.df.iterrows():
            if row['profit_margin'] < 20:
                self.alerts.append({
                    'priority': 'MEDIUM',
                    'product': row['product_name'],
                    'message': f"Profit margin is only {row['profit_margin']:.1f}%.",
                    'action': "Review pricing or supplier costs."
                })
        # Dead stock
        dead_total = self.df[self.df['is_dead']]['stock_value'].sum()
        if dead_total > 0:
            self.alerts.append({
                'priority': 'HIGH',
                'product': 'Multiple products',
                'message': f"R{dead_total:.2f} tied up in dead stock (no recent sales).",
                'action': "Clear out these items via discounts or returns."
            })

    def _generate_recommendations(self):
        """Compile a list of recommended next steps."""
        # Order recommendations from low-stock alerts
        for alert in self.alerts:
            if alert['priority'] == 'HIGH' and 'Order' in alert.get('action', ''):
                self.recommendations.append(f"🔴 {alert['product']}: {alert['action']}")
        # Overstock action
        for alert in self.alerts:
            if alert['priority'] == 'MEDIUM' and 'overstock' in alert['message'].lower():
                self.recommendations.append(f"🟡 {alert['product']}: {alert['action']}")
        # Declining demand action
        for alert in self.alerts:
            if 'declining' in alert['message']:
                self.recommendations.append(f"🟡 {alert['product']}: {alert['action']}")
        # Dead stock action
        for alert in self.alerts:
            if 'dead stock' in alert['message']:
                self.recommendations.append(f"🔴 {alert['product']}: {alert['action']}")

    def summary_report(self) -> str:
        """Generate a human-readable dashboard."""
        lines = []
        lines.append("=" * 60)
        lines.append("📊 INVENTORY AI – DAILY BRIEFING")
        lines.append("=" * 60)

        # Money tied up
        total_value = self.df['stock_value'].sum()
        lines.append(f"💰 Total inventory value: R{total_value:,.2f}")

        # Products at risk (low stock)
        low_stock = self.df[self.df['current_stock'] < self.df['reorder_point']]
        if not low_stock.empty:
            lines.append("\n🔴 HIGH PRIORITY – Low stock")
            for _, row in low_stock.iterrows():
                lines.append(f"  • {row['product_name']}: {row['current_stock']} units "
                             f"({row['days_of_stock']:.1f} days left) – order now.")
        else:
            lines.append("\n✅ No critical stock shortages.")

        # Overstocked
        overstock = self.df[self.df['days_of_stock'] > 90]
        if not overstock.empty:
            lines.append("\n🟡 MEDIUM PRIORITY – Overstocked")
            for _, row in overstock.iterrows():
                lines.append(f"  • {row['product_name']}: {row['current_stock']} units "
                             f"({row['days_of_stock']:.0f} days) – value R{row['stock_value']:,.2f}")

        # Dead stock
        dead = self.df[self.df['is_dead']]
        if not dead.empty:
            lines.append("\n🔴 DEAD STOCK DETECTED")
            for _, row in dead.iterrows():
                lines.append(f"  • {row['product_name']}: R{row['stock_value']:,.2f} tied up – no recent sales.")

        # Recommendations
        if self.recommendations:
            lines.append("\n💡 RECOMMENDED ACTIONS")
            for rec in self.recommendations:
                lines.append(f"  • {rec}")
        else:
            lines.append("\n✅ No specific actions required.")

        # Opportunities (increasing demand)
        inc = self.df[self.df['demand_trend'] > 0.5]
        if not inc.empty:
            lines.append("\n🟢 OPPORTUNITIES")
            for _, row in inc.iterrows():
                lines.append(f"  • {row['product_name']}: demand rising (+{row['demand_trend']:.1f} units/day). "
                             "Consider stocking up.")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def export_alerts(self) -> List[Dict]:
        """Return alerts as dicts for further processing (e.g., JSON)."""
        return self.alerts


# ------------------------------------------------------------
# 3. MAIN EXECUTION
# ------------------------------------------------------------
def main(csv_path=None):
    if csv_path:
        df = pd.read_csv(csv_path)
    else:
        # Use sample data
        df = pd.read_csv(StringIO(SAMPLE_CSV))

    # Initialise and run
    ai = InventoryAI(df)
    alerts, recs = ai.run_analysis()

    # Print summary
    print(ai.summary_report())

    # Optionally, export alerts
    # print("\nAlerts (JSON):", ai.export_alerts())

if __name__ == "__main__":
    # You can pass a CSV file path as argument, e.g.:
    # main("my_inventory.csv")
    main()   # uses sample data
