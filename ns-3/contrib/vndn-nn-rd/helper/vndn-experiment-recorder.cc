#include "vndn-experiment-recorder.h"
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
  for (auto *stream : {&m_requestOutput, &m_mobilityOutput, &m_attemptOutput})
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
             << nowNs << "}\n";
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
