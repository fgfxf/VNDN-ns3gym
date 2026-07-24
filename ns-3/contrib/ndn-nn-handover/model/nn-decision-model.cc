/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#include "nn-decision-model.h"

#include <ns3/log.h>

NS_LOG_COMPONENT_DEFINE ("ndn.NnDecisionModel");

namespace ns3 {
namespace nnhandover {

// The TypeId objects are fully defined inline in the header (GetTypeId is a
// static function that returns a function-local static TypeId). This .cc file
// exists so that:
//   1. the NS_LOG_COMPONENT_DEFINE symbol has a translation unit to live in,
//   2. waf has a source file to compile for this logical unit, and
//   3. future non-inline implementations (e.g. a libtorch backend) can be
//      placed here without changing the build system.

NS_OBJECT_ENSURE_REGISTERED (NnDecisionModel);
NS_OBJECT_ENSURE_REGISTERED (NnHeuristicDecisionModel);

} // namespace nnhandover
} // namespace ns3
