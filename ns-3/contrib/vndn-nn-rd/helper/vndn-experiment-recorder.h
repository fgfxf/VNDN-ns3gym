#ifndef VNDN_EXPERIMENT_RECORDER_H
#define VNDN_EXPERIMENT_RECORDER_H

#include <cstdint>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

namespace vanet {

/** Application observations only. No observation field is serialized on the network. */
class VndnExperimentRecorder
{
public:
  struct PlannedRequest
  {
    uint64_t sequence;
    uint64_t sendTimeNs;
  };
  struct Config
  {
    std::string outputDirectory;
    uint64_t startNs = 0;
    uint64_t endNs = 0;
    uint64_t drainEndNs = 0;
    uint64_t mobilitySampleNs = 100000000;
    std::map<std::string, std::vector<PlannedRequest>> requestPlan;
  };
  struct Request
  {
    std::string requestId;
    std::string name;
    std::string vehicleId;
    uint32_t nodeId;
    uint64_t sequence;
    uint64_t sendNs;
    uint64_t deadlineNs;
    std::string terminal;
  };

  explicit VndnExperimentRecorder (const Config &config);
  ~VndnExperimentRecorder ();
  VndnExperimentRecorder (const VndnExperimentRecorder &) = delete;
  VndnExperimentRecorder &operator= (const VndnExperimentRecorder &) = delete;
  static VndnExperimentRecorder *GetActive ();
  static void SetActive (VndnExperimentRecorder *recorder);
  const Config &GetConfig () const;
  const std::vector<PlannedRequest> &GetPlan (const std::string &vehicleId) const;
  bool RecordGenerated (uint64_t nowNs, const std::string &name,
                        const std::string &vehicleId, uint32_t nodeId,
                        uint64_t sequence, int64_t rsuId);
  bool RecordTerminal (uint64_t nowNs, const std::string &name,
                       const std::string &status, int64_t rsuId);
  void RecordMobility (uint64_t nowNs, const std::string &event,
                       const std::string &vehicleId, uint32_t nodeId,
                       double x, double y, double speedMps,
                       int64_t rsuId, int64_t previousRsuId);
  void RecordDataAttempt (uint64_t nowNs, const std::string &name,
                          uint32_t sourceNode, int64_t targetNode,
                          const std::string &reason,
                          const std::string &parentAttemptId = "");
  void RecordWirelessSubmission (uint64_t nowNs, const std::string &name,
                                 uint32_t sourceNode, uint32_t targetNode);
  uint64_t GetGeneratedCount () const;
  uint64_t GetTerminalCount () const;
  uint64_t GetExtraAttemptCount () const;
  const Request *FindRequest (const std::string &name) const;
  bool Finalize (uint64_t nowNs);

private:
  void WriteRequest (uint64_t nowNs, const std::string &event,
                     const Request &request, int64_t rsuId);
  Config m_config;
  std::map<std::string, Request> m_requests;
  std::set<std::string> m_requestIds;
  std::set<std::tuple<std::string, uint32_t, uint32_t>> m_wirelessSubmissions;
  std::ofstream m_requestOutput;
  std::ofstream m_mobilityOutput;
  std::ofstream m_attemptOutput;
  uint64_t m_terminalCount = 0;
  uint64_t m_attemptCount = 0;
  bool m_finalized = false;
  bool m_complete = false;
  static VndnExperimentRecorder *s_active;
};

} // namespace vanet
#endif
