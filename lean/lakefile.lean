import Lake
open Lake DSL

package «veriphys» where
  moreLeanArgs := #["-DwarningAsError=false"]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.19.0"

lean_lib VeriPhys
