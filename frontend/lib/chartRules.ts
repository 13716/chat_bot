/**
 * Rule-based Chart Selector
 * ─────────────────────────
 * Chọn loại biểu đồ theo ĐẶC TÍNH DỮ LIỆU + CÂU HỎI PHÂN TÍCH,
 * thay vì gán cứng hoặc để LLM tự đoán (bất ổn).
 *
 * Nguyên tắc trực quan hóa chuẩn:
 *   - Chuỗi thời gian        → đường / miền (area)
 *   - Phân rã chênh lệch     → waterfall
 *   - Cơ cấu / tỷ trọng      → tròn (pie) [+ cột để so sánh tuyệt đối]
 *   - So sánh cặp giá trị    → cột nhóm (grouped bar)
 *   - So sánh danh mục       → cột (bar)
 */

export type ChartKind = "bar" | "groupedBar" | "pie" | "area" | "waterfall"

export interface DataShape {
  /** Bản chất phân tích */
  intent: "composition" | "comparison" | "variance" | "trend"
  /** Số nhóm / danh mục */
  categories: number
  /** Dữ liệu là "phần của tổng" (cộng lại = 100%)? → ứng viên cho pie */
  partsOfWhole: boolean
  /** Có trục thời gian (tháng/quý/năm)? → ứng viên cho area */
  hasTime: boolean
  /** Có cặp giá trị so sánh (vd Actual vs Budget, Thực tế vs Ngưỡng)? */
  paired: boolean
}

/**
 * Trả về DANH SÁCH chart nên vẽ, theo thứ tự ưu tiên hiển thị.
 * Pie chỉ dùng khi là cơ cấu và đủ ít nhóm (≤6) — nhiều nhóm thì pie rối, dùng cột.
 */
export function recommendCharts(s: DataShape): ChartKind[] {
  // 1. Chuỗi thời gian → miền (xu hướng)
  if (s.hasTime || s.intent === "trend") return ["area"]

  // 2. Phân rã chênh lệch tăng/giảm → waterfall (kèm cột nhóm nếu có cặp giá trị)
  if (s.intent === "variance") return s.paired ? ["groupedBar", "waterfall"] : ["waterfall"]

  // 3. Cơ cấu / tỷ trọng, đủ ít nhóm → tròn + cột (pie xem tỷ trọng, cột so sánh tuyệt đối)
  if (s.intent === "composition" && s.partsOfWhole) {
    return s.categories <= 6 ? ["pie", "bar"] : ["bar"]
  }

  // 4. So sánh có cặp giá trị → cột nhóm
  if (s.paired) return ["groupedBar"]

  // 5. Mặc định: so sánh danh mục → cột
  return ["bar"]
}

/** Nhãn tiếng Việt cho từng loại chart (hiển thị "biểu đồ đề xuất") */
export const CHART_LABEL: Record<ChartKind, string> = {
  bar: "Cột",
  groupedBar: "Cột nhóm",
  pie: "Tròn",
  area: "Miền",
  waterfall: "Waterfall",
}
