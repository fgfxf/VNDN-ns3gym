#include "vndn-experiment-recorder.h"
#include "../src/json/single_include/nlohmann/json.hpp"
#include <cmath>
#include <cstdio>
#include <iomanip>
#include <limits>
#include <stdexcept>

namespace vanet {
namespace {
constexpr uint64_t REQUEST_LIFETIME_NS = 3000000000ULL;

std::string
Csv (const std::string &value)
{
  if (value.find_first_of (",\"\r\n") == std::string::npos)
    return value;
  std::string escaped = "\"";
  for (char c : value)
    {
      escaped += c;
      if (c == '"') escaped += '"';
    }
  return escaped + '"';
}
}

VndnExperimentRecorder *VndnExperimentRecorder::s_active = nullptr;
VndnExperimentRecorder::VndnExperimentRecorder (const Config &config) : m_config (config)
{
  if (config.startNs >= config.endNs ||
      config.endNs > std::numeric_limits<uint64_t>::max () - REQUEST_LIFETIME_NS ||
      config.drainEndNs < config.endNs + REQUEST_LIFETIME_NS ||
      config.mobilitySampleNs == 0)
    throw std::invalid_argument ("Invalid experiment measurement/drain window");
  if (config.trainingSnapshots &&
      (config.outputDirectory.empty () || config.runId.empty () ||
       (config.scenario != "circle" && config.scenario != "grid" &&
        config.scenario != "spidermap")))
    throw std::invalid_argument ("Training snapshots require an output directory, run and scenario");
  if (config.resourceObservations && config.outputDirectory.empty ())
    throw std::invalid_argument ("Resource observations require an output directory");
  for (const auto &vehicle : config.requestPlan)
    {
      std::set<uint64_t> sequences;
      uint64_t previous = 0;
      for (const auto &request : vehicle.second)
        {
          if (request.sendTimeNs < config.startNs || request.sendTimeNs >= config.endNs ||
              request.sendTimeNs < previous || !sequences.insert (request.sequence).second)
            throw std::invalid_argument ("Invalid or unordered vehicle request plan");
          previous = request.sendTimeNs;
        }
    }
  if (!config.outputDirectory.empty ())
    {
      const auto open = [&] (std::ofstream &stream, const std::string &name) {
        const std::string path = config.outputDirectory + "/" + name;
        if (std::ifstream (path).good ())
          throw std::runtime_error ("Refusing to overwrite experiment log: " + path);
        stream.exceptions (std::ios::failbit | std::ios::badbit);
        stream.open (path, std::ios::out);
      };
      open (m_requestOutput, "request-events.csv");
      open (m_mobilityOutput, "mobility-events.csv");
      open (m_attemptOutput, "data-attempts.csv");
      open (m_neuralOutput, "neural-decisions.jsonl");
      if (config.trainingSnapshots)
        open (m_trainingOutput, "training-observations.jsonl");
      if (config.resourceObservations)
        {
          open (m_stateOutput, "rsu-state.csv");
          open (m_helloOutput, "hello-payloads.csv");
          m_stateOutput << "time_ns,event,rsu_id,present_vehicles,cache_vehicle_entries,"
                           "cache_name_entries,cache_edges,reverse_cache_edges,mac_entries,"
                           "next_rsu_entries,history_vehicles,history_records,history_timestamp_records\n";
          m_helloOutput << "time_ns,obu_node_id,rsu_id,category,content_bytes,wire_bytes,"
                           "cache_items,added_items,removed_items\n";
        }
      m_requestOutput << "time_ns,event,request_id,name,vehicle_id,node_id,sequence,"
                         "send_ns,deadline_ns,rsu_id\n";
      m_mobilityOutput << "time_ns,event,vehicle_id,node_id,x,y,speed_mps,rsu_id,"
                          "previous_rsu_id\n";
      m_attemptOutput << "time_ns,attempt_id,parent_attempt_id,name,source_node,"
                         "target_node,reason,stage\n";
      m_mobilityOutput << std::setprecision (17);
    }
}
VndnExperimentRecorder::~VndnExperimentRecorder ()
{
  if (s_active == this) s_active = nullptr;
}
VndnExperimentRecorder *VndnExperimentRecorder::GetActive () { return s_active; }
void VndnExperimentRecorder::SetActive (VndnExperimentRecorder *recorder) { s_active = recorder; }
const VndnExperimentRecorder::Config &VndnExperimentRecorder::GetConfig () const { return m_config; }
const std::vector<VndnExperimentRecorder::PlannedRequest> &
VndnExperimentRecorder::GetPlan (const std::string &id) const { return m_config.requestPlan.at (id); }
bool
VndnExperimentRecorder::RecordGenerated (uint64_t nowNs, const std::string &name,
    const std::string &vehicleId, uint32_t nodeId, uint64_t sequence, int64_t rsuId)
{
  const std::string requestId = vehicleId + ":" + std::to_string (sequence);
  if (m_finalized || nowNs < m_config.startNs || nowNs >= m_config.endNs ||
      name.empty () || vehicleId.empty () || m_requests.count (name) != 0 ||
      m_requestIds.count (requestId) != 0)
    return false;
  Request request {requestId, name, vehicleId, nodeId, sequence, nowNs,
                   nowNs + REQUEST_LIFETIME_NS, ""};
  m_requests.emplace (name, request);
  m_requestIds.insert (requestId);
  WriteRequest (nowNs, "GENERATED", request, rsuId);
  return true;
}

bool
VndnExperimentRecorder::RecordTerminal (uint64_t nowNs, const std::string &name,
    const std::string &status, int64_t rsuId)
{
  if (m_finalized) return false;
  auto found = m_requests.find (name);
  if (found == m_requests.end ()) return false;
  Request &request = found->second;
  if (nowNs < request.sendNs)
    throw std::invalid_argument ("Request result precedes generation");
  if (status != "DATA" && status != "TIMEOUT" && status != "NACK" && status != "STOPPED")
    throw std::invalid_argument ("Unknown request terminal status: " + status);
  if (status == "DATA" && (!request.terminal.empty () || nowNs > request.deadlineNs))
    {
      if (nowNs > request.deadlineNs && request.terminal.empty ())
        {
          // Face may consume its pending Interest when this late Data arrives,
          // so a later onTimeout callback is not guaranteed. Its expiration is
          // fixed by the request deadline, independently of callback order.
          request.terminal = "TIMEOUT";
          ++m_terminalCount;
          WriteRequest (request.deadlineNs, "TIMEOUT", request, -1);
        }
      const std::string diagnostic =
          nowNs > request.deadlineNs ? "LATE_DATA" :
          request.terminal == "DATA" ? "DUPLICATE_DATA" : "POST_TERMINAL_DATA";
      WriteRequest (nowNs, diagnostic, request, rsuId);
      return false;
    }
  if (!request.terminal.empty ()) return false;
  if (status == "TIMEOUT" && nowNs < request.deadlineNs)
    throw std::invalid_argument ("Timeout precedes request deadline");
  request.terminal = status;
  ++m_terminalCount;
  WriteRequest (nowNs, status, request, rsuId);
  return true;
}

void
VndnExperimentRecorder::RecordMobility (uint64_t nowNs, const std::string &event,
    const std::string &vehicleId, uint32_t nodeId, double x, double y,
    double speedMps, int64_t rsuId, int64_t previousRsuId)
{
  if (m_finalized) throw std::logic_error ("Mobility after recorder finalization");
  if (event != "ENTER" && event != "SAMPLE" && event != "ASSOCIATION" && event != "EXIT")
    throw std::invalid_argument ("Unknown mobility event");
  if (!std::isfinite (x) || !std::isfinite (y) || !std::isfinite (speedMps))
    throw std::invalid_argument ("Non-finite SUMO mobility observation");
  if (m_mobilityOutput.is_open ())
    m_mobilityOutput << nowNs << ',' << event << ',' << Csv (vehicleId) << ','
                     << nodeId << ',' << x << ',' << y << ',' << speedMps << ','
                     << rsuId << ',' << previousRsuId << '\n';
}

void
VndnExperimentRecorder::RecordDataAttempt (uint64_t nowNs, const std::string &name,
    uint32_t sourceNode, int64_t targetNode, const std::string &reason,
    const std::string &parentAttemptId)
{
  if (m_finalized || nowNs < m_config.startNs || nowNs >= m_config.drainEndNs)
    return;
  if (reason != "PREDICTIVE_EXTRA" && reason != "REACTIVE_RELAY" &&
      reason != "REPEATED_SUBMIT")
    throw std::invalid_argument ("Unknown extra Data application attempt reason");
  ++m_attemptCount;
  if (m_attemptOutput.is_open ())
    m_attemptOutput << nowNs << ",a" << m_attemptCount << ','
                    << Csv (parentAttemptId.empty () ? "-" : parentAttemptId)
                    << ',' << Csv (name) << ',' << sourceNode << ',' << targetNode
                    << ',' << reason << ",APP_SUBMIT\n";
}

void
VndnExperimentRecorder::RecordWirelessSubmission (uint64_t nowNs,
    const std::string &name, uint32_t sourceNode, uint32_t targetNode)
{
  if (m_finalized || nowNs < m_config.startNs || nowNs >= m_config.drainEndNs)
    return;
  if (!m_wirelessSubmissions.emplace (name, sourceNode, targetNode).second)
    RecordDataAttempt (nowNs, name, sourceNode, targetNode, "REPEATED_SUBMIT");
}

void
VndnExperimentRecorder::RecordTrainingSnapshot (
    uint64_t nowNs, const std::string &name, uint32_t obuNodeId,
    uint32_t sourceRsuId, uint64_t incomingFaceId,
    const std::vector<uint32_t> &candidateRsuIds,
    const std::vector<std::array<double, 6>> &features,
    const std::vector<uint64_t> &helloReceiveTimesNs)
{
  if (!m_config.trainingSnapshots)
    return;
  if (m_finalized)
    throw std::logic_error ("Training observation after recorder finalization");
  using Json = nlohmann::json;
  const uint64_t event = ++m_trainingRows;
  const Request *request = FindRequest (name);
  std::string reason;
  bool first = false;
  Json firstEvent = nullptr;
  if (request == nullptr)
    reason = "UNKNOWN_REQUEST";
  else if (request->nodeId != obuNodeId)
    reason = "OBU_ID_MISMATCH";
  else
    {
      const auto inserted = m_firstTrainingEvents.emplace (
          std::make_tuple (name, obuNodeId, sourceRsuId), event);
      first = inserted.second;
      firstEvent = inserted.first->second;
      if (!first)
        reason = "DUPLICATE_SOURCE_REQUEST";
      else if (nowNs < request->sendNs)
        reason = "DECISION_BEFORE_SEND";
      else if (nowNs > request->deadlineNs)
        reason = "DECISION_AFTER_DEADLINE";
    }
  if (reason.empty () &&
      (features.size () != 10 || helloReceiveTimesNs.size () > 10))
    reason = "INVALID_OBSERVATION_SHAPE";
  uint64_t previous = 0;
  for (const uint64_t received : helloReceiveTimesNs)
    {
      if (reason.empty () && (received < previous || received > nowNs))
        reason = "INVALID_HISTORY_TIMES";
      previous = received;
    }
  for (const auto &state : features)
    for (const double value : state)
      if (reason.empty ())
        {
          if (!std::isfinite (value))
            reason = "NONFINITE_FEATURE";
          else if (!std::isfinite (static_cast<float> (value)))
            reason = "FLOAT32_OVERFLOW";
        }
  if (reason.empty ())
    ++m_trainingEligible;
  Json row = {
    {"schema_version", 1}, {"observation_contract", "rsu-hello-window-v1"},
    {"scenario", m_config.scenario}, {"run_id", m_config.runId},
    {"name", name}, {"obu_node_id", obuNodeId}, {"source_rsu_id", sourceRsuId},
    {"incoming_face_id", incomingFaceId}, {"decision_event_id", event},
    {"decision_time_ns", nowNs}, {"candidate_rsu_ids", candidateRsuIds},
    {"features", features}, {"hello_receive_times_ns", helloReceiveTimesNs},
    {"actual_history_length", helloReceiveTimesNs.size ()},
    {"padding_count", helloReceiveTimesNs.size () <= 10 ? 10 - helloReceiveTimesNs.size () : 0},
    {"first_for_source_request", first}, {"first_decision_event_id", firstEvent},
    {"sample_exclusion_reason", reason},
    {"history_age_ns", helloReceiveTimesNs.empty () || helloReceiveTimesNs.back () > nowNs
                           ? Json (nullptr) : Json (nowNs - helloReceiveTimesNs.back ())}
  };
  row["request_id"] = request == nullptr ? Json (nullptr) : Json (request->requestId);
  row["vehicle_id"] = request == nullptr ? Json (nullptr) : Json (request->vehicleId);
  row["send_time_ns"] = request == nullptr ? Json (nullptr) : Json (request->sendNs);
  row["deadline_ns"] = request == nullptr ? Json (nullptr) : Json (request->deadlineNs);
  m_trainingOutput << row.dump () << '\n';
}

void
VndnExperimentRecorder::RecordNeuralDecision (
    uint64_t nowNs, const std::string &name, uint32_t obuNodeId, uint32_t sourceRsuId,
    const std::vector<uint32_t> &candidateRsuIds, const std::vector<float> &probabilities,
    const std::vector<uint32_t> &selectedRsuIds, double probabilityGap,
    double minSecondProbability, const std::string &actionStatus)
{
  if (m_finalized)
    throw std::logic_error ("Neural decision after recorder finalization");
  if (actionStatus != "ACCEPTED" && actionStatus != "FALLBACK_INVALID_ACTION")
    throw std::invalid_argument ("Unknown neural action observation status");
  using Json = nlohmann::json;
  const Request *request = FindRequest (name);
  Json row = {
    {"schema_version", 1}, {"scenario", m_config.scenario}, {"run_id", m_config.runId},
    {"decision_event_id", ++m_neuralDecisions}, {"decision_time_ns", nowNs},
    {"name", name}, {"obu_node_id", obuNodeId}, {"source_rsu_id", sourceRsuId},
    {"candidate_rsu_ids", candidateRsuIds}, {"probabilities", probabilities},
    {"selected_rsu_ids", selectedRsuIds}, {"dual_path_probability_gap", probabilityGap},
    {"dual_path_min_second_probability", minSecondProbability}, {"action_status", actionStatus}
  };
  row["request_id"] = request == nullptr ? Json (nullptr) : Json (request->requestId);
  row["vehicle_id"] = request == nullptr ? Json (nullptr) : Json (request->vehicleId);
  if (m_neuralOutput.is_open ())
    m_neuralOutput << row.dump () << '\n';
}

void
VndnExperimentRecorder::RecordRsuState (uint64_t nowNs, const std::string &event,
    uint32_t rsuId, const std::array<uint64_t, 10> &counts)
{
  if (!m_config.resourceObservations) return;
  if (m_finalized) throw std::logic_error ("Resource state after recorder finalization");
  if (event != "START" && event != "CHANGE" && event != "STOP")
    throw std::invalid_argument ("Unknown RSU resource event");
  const auto previous = m_lastRsuState.find (rsuId);
  if (event == "CHANGE" && previous != m_lastRsuState.end () && previous->second == counts)
    return;
  m_lastRsuState[rsuId] = counts;
  m_stateOutput << nowNs << ',' << event << ',' << rsuId;
  for (const auto count : counts) m_stateOutput << ',' << count;
  m_stateOutput << '\n';
  ++m_stateRows;
}

void
VndnExperimentRecorder::RecordHelloPayload (uint64_t nowNs, uint32_t obuNodeId,
    int64_t rsuId, const std::string &category, uint64_t contentBytes,
    uint64_t wireBytes, uint64_t cacheItems, uint64_t addedItems, uint64_t removedItems)
{
  if (!m_config.resourceObservations) return;
  if (m_finalized) throw std::logic_error ("Hello observation after recorder finalization");
  if (category != "registration" && category != "delta" &&
      category != "unchanged" && category != "cache_disabled")
    throw std::invalid_argument ("Unknown hello payload category");
  if (wireBytes < contentBytes)
    throw std::invalid_argument ("Encoded Data cannot be smaller than its content");
  m_helloOutput << nowNs << ',' << obuNodeId << ',' << rsuId << ',' << category << ','
                << contentBytes << ',' << wireBytes << ',' << cacheItems << ','
                << addedItems << ',' << removedItems << '\n';
  ++m_helloRows;
}

uint64_t VndnExperimentRecorder::GetGeneratedCount () const { return m_requests.size (); }
uint64_t VndnExperimentRecorder::GetTerminalCount () const { return m_terminalCount; }
uint64_t VndnExperimentRecorder::GetExtraAttemptCount () const { return m_attemptCount; }
const VndnExperimentRecorder::Request *
VndnExperimentRecorder::FindRequest (const std::string &name) const
{
  const auto found = m_requests.find (name);
  return found == m_requests.end () ? nullptr : &found->second;
}

bool
VndnExperimentRecorder::Finalize (uint64_t nowNs)
{
  if (m_finalized) return m_complete;
  uint64_t planned = 0;
  for (const auto &entry : m_config.requestPlan) planned += entry.second.size ();
  m_complete = nowNs >= m_config.drainEndNs && m_terminalCount == m_requests.size () &&
               m_requests.size () == planned;
  for (auto *stream : {&m_requestOutput, &m_mobilityOutput, &m_attemptOutput,
                       &m_trainingOutput, &m_neuralOutput, &m_stateOutput, &m_helloOutput})
    if (stream->is_open ())
      {
        stream->flush ();
        stream->close ();
      }
  if (!m_config.outputDirectory.empty ())
    {
      const std::string path = m_config.outputDirectory + "/recorder-complete.json";
      const std::string temporary = path + ".tmp";
      std::ofstream marker;
      marker.exceptions (std::ios::failbit | std::ios::badbit);
      marker.open (temporary);
      marker << "{\"schema_version\":1,\"complete\":" << (m_complete ? "true" : "false")
             << ",\"generated\":" << m_requests.size () << ",\"terminal\":"
             << m_terminalCount << ",\"planned\":" << planned
             << ",\"extra_attempts\":" << m_attemptCount << ",\"final_time_ns\":"
             << nowNs << ",\"training_snapshots\":"
             << (m_config.trainingSnapshots ? "true" : "false")
             << ",\"training_snapshot_rows\":" << m_trainingRows
             << ",\"training_snapshot_eligible\":" << m_trainingEligible
             << ",\"training_snapshot_excluded\":" << m_trainingRows - m_trainingEligible
             << ",\"neural_decision_rows\":" << m_neuralDecisions
             << ",\"resource_observations\":" << (m_config.resourceObservations ? "true" : "false")
             << ",\"rsu_state_rows\":" << m_stateRows
             << ",\"hello_payload_rows\":" << m_helloRows
             << "}\n";
      marker.close ();
      if (std::rename (temporary.c_str (), path.c_str ()) != 0)
        throw std::runtime_error ("Cannot finalize experiment completion marker");
    }
  m_finalized = true;
  return m_complete;
}

void
VndnExperimentRecorder::WriteRequest (uint64_t nowNs, const std::string &event,
    const Request &request, int64_t rsuId)
{
  if (m_requestOutput.is_open ())
    m_requestOutput << nowNs << ',' << event << ',' << Csv (request.requestId) << ','
                    << Csv (request.name) << ',' << Csv (request.vehicleId) << ','
                    << request.nodeId << ',' << request.sequence << ',' << request.sendNs
                    << ',' << request.deadlineNs << ',' << rsuId << '\n';
}
} // namespace vanet
