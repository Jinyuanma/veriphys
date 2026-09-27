import Mathlib.Data.Real.Basic
import Mathlib.Tactic.Linarith

namespace VeriPhys

/- The V0 core treats physical quantities as real numbers. -/
theorem newton_second_law {m a F : ℝ} (h : F = m * a) : F = m * a := by
  exact h

theorem free_fall {m a g F : ℝ} (hm : m ≠ 0)
    (h_newton : F = m * a) (h_gravity : F = m * g) : a = g := by
  have h : m * a = m * g := by
    calc
      m * a = F := h_newton.symm
      _ = m * g := h_gravity
  have h_sub : m * (a - g) = 0 := by
    nlinarith [h]
  rcases mul_eq_zero.mp h_sub with hm_zero | h_diff
  · exact (hm hm_zero).elim
  · exact sub_eq_zero.mp h_diff

end VeriPhys
