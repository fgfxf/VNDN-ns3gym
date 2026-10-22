/* Neural-only hello wire codec. No class layout or model-input changes. */
#ifndef VNDN_HELLO_WIRE_H
#define VNDN_HELLO_WIRE_H

#include "src/json/single_include/nlohmann/json.hpp"
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>

namespace vanet {
namespace hello_wire {

using Json = nlohmann::json;

inline bool
IsIntegerInRange (const Json &value, int64_t minimum, int64_t maximum)
{
  if (!value.is_number_integer ())
    return false;
  if (value.is_number_unsigned ())
    {
      const uint64_t number = value.get<uint64_t> ();
      return number <= static_cast<uint64_t> (maximum) &&
             (minimum <= 0 || number >= static_cast<uint64_t> (minimum));
    }
  const int64_t number = value.get<int64_t> ();
  return number >= minimum && number <= maximum;
}

inline void
Require (bool condition)
{
  if (!condition)
    throw std::invalid_argument ("Invalid VNH1 hello payload");
}

inline void
ValidateNames (const Json &names)
{
  Require (names.is_array ());
  for (const auto &name : names)
    Require (name.is_string ());
}

inline void
ValidateEnvelope (const Json &envelope)
{
  Require (envelope.is_array () && envelope.size () == 4);
  Require (IsIntegerInRange (envelope[0], 1, 1));
  const auto &state = envelope[1];
  Require (state.is_array () && state.size () == 6);
  for (size_t index = 0; index < 5; ++index)
    Require (state[index].is_number () &&
             std::isfinite (state[index].get<double> ()));
  Require (IsIntegerInRange (state[5], std::numeric_limits<int>::min (),
                            std::numeric_limits<int>::max ()));
  Require (IsIntegerInRange (envelope[2], std::numeric_limits<int64_t>::min (),
                            std::numeric_limits<int64_t>::max ()));

  const auto &cache = envelope[3];
  Require (cache.is_object ());
  for (auto field = cache.begin (); field != cache.end (); ++field)
    Require (field.key () == "CsUpdate" || field.key () == "CsList" ||
             field.key () == "CsAdded" || field.key () == "CsRemoved");
  if (cache.empty ())
    return;
  Require (cache.contains ("CsUpdate") && cache["CsUpdate"].is_boolean ());
  if (cache["CsUpdate"].get<bool> ())
    {
      Require (!cache.contains ("CsList") && cache.contains ("CsAdded") &&
               cache.contains ("CsRemoved"));
      ValidateNames (cache["CsAdded"]);
      ValidateNames (cache["CsRemoved"]);
    }
  else
    {
      Require (cache.contains ("CsList") && !cache.contains ("CsAdded") &&
               !cache.contains ("CsRemoved"));
      ValidateNames (cache["CsList"]);
    }
}

inline std::string
Encode (const Json &hello)
{
  Json state = Json::array ({hello.at ("LocateX"), hello.at ("LocateY"),
                            hello.at ("Speed"), hello.at ("Acceleration"),
                            hello.at ("Angle"), hello.at ("LaneIndex")});
  Json cache = Json::object ();
  for (const char *field : {"CsUpdate", "CsList", "CsAdded", "CsRemoved"})
    if (hello.contains (field))
      cache[field] = hello.at (field);
  const Json envelope = Json::array ({1, state, hello.at ("NextRsu"), cache});
  ValidateEnvelope (envelope);
  const auto binary = Json::to_cbor (envelope);
  return std::string ("VNH1") + std::string (binary.begin (), binary.end ());
}

inline Json
Decode (const std::string &wire)
{
  if (wire.compare (0, 3, "VNH") != 0)
    return Json::parse (wire); // Preserve all existing legacy JSON semantics.
  Require (wire.compare (0, 4, "VNH1") == 0 && wire.size () > 4);
  const Json envelope = Json::from_cbor (wire.begin () + 4, wire.end ());
  ValidateEnvelope (envelope);

  // Rebuild the existing object before any caller-owned state is changed.
  Json hello = envelope[3];
  const char *fields[] = {"LocateX", "LocateY", "Speed", "Acceleration", "Angle", "LaneIndex"};
  for (size_t index = 0; index < 6; ++index)
    hello[fields[index]] = envelope[1][index];
  hello["NextRsu"] = envelope[2];
  return hello;
}

} // namespace hello_wire
} // namespace vanet

#endif
