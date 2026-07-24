/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_DECISION_MODEL_H
#define NN_DECISION_MODEL_H

#include "vehicle-mobility-info.h"

#include <ns3/core-module.h>
#include <ns3/object.h>

#include <string>

namespace ns3 {
namespace nnhandover {

/**
 * @brief Result of a neural-network routing decision.
 *
 * The decision tells the common backhaul router which RSU (i.e. which face /
 * next-hop) should be used to forward the Data packets destined to the moving
 * vehicle, after the vehicle has handed over between two RSUs.
 */
struct NnDecision
{
  std::string vehicleId;     ///< vehicle the decision applies to
  std::string chosenRsuId;   ///< RSU that should receive the downlink Data
  double confidence = 0.0;   ///< NN output confidence in [0,1]
  std::string reason;        ///< human readable explanation (for logging)
};

/**
 * @brief Abstract base class for the neural-network decision model.
 *
 * This is the pluggable "brain" of the framework. The default implementation
 * (NnHeuristicDecisionModel) is a lightweight rule-based stand-in so that the
 * whole framework can be compiled and exercised without any external ML
 * library. A real deployment subclasses this and plugs in an inference engine
 * (e.g. libtorch, ONNX Runtime, TensorFlow Lite C API, or a Python sidecar).
 *
 * The model is an ns3::Object so that it can be created via CreateObject and
 * aggregated / passed around through ns-3 attributes if desired.
 */
class NnDecisionModel : public Object
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid = TypeId ("ns3::nnhandover::NnDecisionModel")
                            .SetParent<Object> ()
                            .SetGroupName ("NnHandover");
    return tid;
  }

  /**
   * @brief Run the neural-network inference on the collected mobility info.
   *
   * @param info  vehicle driving information reported by the OBU
   * @return      the routing decision (which RSU to use for downlink Data)
   *
   * Implementations MUST be deterministic for a given input during a single
   * simulation run, and MUST be fast (it is called in the forwarding path).
   */
  virtual NnDecision
  Decide (const VehicleMobilityInfo &info) = 0;

  /// Human readable name of the model (for logging).
  virtual std::string
  Name () const
  {
    return "NnDecisionModel";
  }
};

/**
 * @brief A simple heuristic stand-in for the neural-network model.
 *
 * It picks the RSU with the stronger RSSI, but biases the decision by the
 * vehicle heading: if the vehicle is moving towards the target RSU and the
 * RSSI gap is small, it proactively switches to the target RSU. This mimics
 * what a small trained classifier would learn, and keeps the framework
 * self-contained.
 */
class NnHeuristicDecisionModel : public NnDecisionModel
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid =
        TypeId ("ns3::nnhandover::NnHeuristicDecisionModel")
            .SetParent<NnDecisionModel> ()
            .SetGroupName ("NnHandover")
            .AddConstructor<NnHeuristicDecisionModel> ()
            .AddAttribute ("RssiHysteresisDb",
                           "RSSI hysteresis margin [dB] that the target RSU must "
                           "exceed before a proactive switch is taken.",
                           DoubleValue (3.0),
                           MakeDoubleAccessor (&NnHeuristicDecisionModel::m_rssiHyst),
                           MakeDoubleChecker<double> ());
    return tid;
  }

  NnDecision
  Decide (const VehicleMobilityInfo &info) override
  {
    NnDecision d;
    d.vehicleId = info.vehicleId;

    double gap = info.targetRssi - info.currentRssi;
    if (gap > m_rssiHyst)
      {
        // target RSU is already clearly better -> switch now
        d.chosenRsuId = info.targetRsuId;
        d.confidence = std::min (1.0, 0.5 + gap / 20.0);
        d.reason = "target-RSSI-dominant";
      }
    else if (gap > -m_rssiHyst && info.speed > 0.5)
      {
        // RSSI is close and the vehicle is moving -> be proactive and switch
        // to the target RSU so that downlink Data follows the vehicle.
        d.chosenRsuId = info.targetRsuId;
        d.confidence = 0.6;
        d.reason = "proactive-handover";
      }
    else
      {
        d.chosenRsuId = info.currentRsuId;
        d.confidence = 1.0 - std::max (0.0, -gap) / 20.0;
        d.reason = "stay-on-current";
      }
    return d;
  }

  std::string
  Name () const override
  {
    return "NnHeuristicDecisionModel";
  }

private:
  double m_rssiHyst = 3.0; ///< RSSI hysteresis margin [dB]
};

} // namespace nnhandover
} // namespace ns3

#endif // NN_DECISION_MODEL_H
