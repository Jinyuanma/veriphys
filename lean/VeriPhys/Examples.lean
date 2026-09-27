import VeriPhys.Basic

namespace VeriPhys

example {m a g F : ℝ} (hm : m ≠ 0)
    (h_newton : F = m * a) (h_gravity : F = m * g) : a = g := by
  exact free_fall hm h_newton h_gravity

end VeriPhys
