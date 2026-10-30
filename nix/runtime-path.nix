{ lib }:
lib.types.addCheck lib.types.str (
  value:
  lib.hasPrefix "/" value
  && value != builtins.storeDir
  && !(lib.hasPrefix "${builtins.storeDir}/" value)
  && !(lib.hasInfix "\n" value)
  && !(lib.hasInfix "\r" value)
)
