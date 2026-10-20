#include "vndn-experiment-config.h"
#include "../src/json/single_include/nlohmann/json.hpp"
#include <rapidxml.hpp>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace vanet {
namespace {

using Json = nlohmann::json;

std::string
ParentPath (const std::string &path)
{
  const auto separator = path.find_last_of ('/');
  return separator == 0 ? "/" : path.substr (0, separator);
}

std::string
AbsolutePath (const std::string &base, const std::string &path)
{
  if (path.empty ())
    throw std::runtime_error ("Experiment paths cannot be empty");
  const std::string combined = path[0] == '/' ? path : base + "/" + path;
  std::istringstream stream (combined);
  std::vector<std::string> parts;
  std::string part;
  while (std::getline (stream, part, '/'))
    {
      if (part.empty () || part == ".")
        continue;
      if (part == "..")
        {
          if (!parts.empty ())
            parts.pop_back ();
        }
      else
        parts.push_back (part);
    }
  std::string result;
  for (const auto &item : parts)
    result += "/" + item;
  return result.empty () ? "/" : result;
}

std::string
ExistingFile (const std::string &base, const std::string &path)
{
  const std::string absolute = AbsolutePath (base, path);
  char *resolved = realpath (absolute.c_str (), nullptr);
  if (resolved == nullptr)
    throw std::runtime_error ("Cannot resolve experiment input: " + absolute);
  const std::string result (resolved);
  free (resolved);
  struct stat attributes;
  if (stat (result.c_str (), &attributes) != 0 || !S_ISREG (attributes.st_mode))
    throw std::runtime_error ("Experiment input is not a regular file: " + result);
  return result;
}

Json
ReadJson (const std::string &path)
{
  std::ifstream stream (path);
  Json value;
  if (!stream)
    throw std::runtime_error ("Cannot read experiment input: " + path);
  stream >> value;
  if (!value.is_object ())
    throw std::runtime_error ("Experiment JSON must be an object: " + path);
  return value;
}

uint64_t
Integer (const Json &value, const std::string &field, uint64_t minimum,
         uint64_t maximum = std::numeric_limits<uint64_t>::max ())
{
  if (!value.is_number_integer () || (value.is_number_integer () &&
      !value.is_number_unsigned () && value.get<int64_t> () < 0))
    throw std::runtime_error (field + " must be a nonnegative integer");
  const uint64_t result = value.get<uint64_t> ();
  if (result < minimum || result > maximum)
    throw std::runtime_error (field + " is outside its supported range");
  return result;
}

uint64_t
TimeNs (const Json &value, const std::string &field)
{
  if (!value.is_number ())
    throw std::runtime_error (field + " must be numeric seconds");
  const double seconds = value.get<double> ();
  const long double nanoseconds = static_cast<long double> (seconds) * 1000000000.0L;
  if (!std::isfinite (seconds) || seconds < 0 ||
      nanoseconds > static_cast<long double> (std::numeric_limits<int64_t>::max ()) - 1)
    throw std::runtime_error (field + " exceeds the ns-3 time range");
  return static_cast<uint64_t> (std::llround (nanoseconds));
}

std::vector<char>
ReadXml (const std::string &path)
{
  std::ifstream input (path);
  if (!input)
    throw std::runtime_error ("Cannot read XML input: " + path);
  std::vector<char> buffer ((std::istreambuf_iterator<char> (input)),
                            std::istreambuf_iterator<char> ());
  buffer.push_back ('\0');
  return buffer;
}

void
CheckSumoRoute (const ExperimentConfig &config)
{
  auto text = ReadXml (config.sumoConfigPath);
  rapidxml::xml_document<> document;
  document.parse<0> (text.data ());
  auto *root = document.first_node ("configuration");
  auto *input = root == nullptr ? nullptr : root->first_node ("input");
  auto *route = input == nullptr ? nullptr : input->first_node ("route-files");
  auto *routeValue = route == nullptr ? nullptr : route->first_attribute ("value");
  if (routeValue == nullptr ||
      ExistingFile (ParentPath (config.sumoConfigPath), routeValue->value ()) !=
          config.routeFilePath)
    throw std::runtime_error ("SUMO must load the same single route_file used by the experiment");
  auto *net = input->first_node ("net-file");
  auto *netValue = net == nullptr ? nullptr : net->first_attribute ("value");
  if (netValue == nullptr)
    throw std::runtime_error ("SUMO configuration must specify its network");
  ExistingFile (ParentPath (config.sumoConfigPath), netValue->value ());
}

void
ReadVehicles (ExperimentConfig &config)
{
  auto text = ReadXml (config.routeFilePath);
  rapidxml::xml_document<> document;
  document.parse<0> (text.data ());
  auto *routes = document.first_node ("routes");
  if (routes == nullptr || routes->first_node ("flow") != nullptr ||
      routes->first_node ("trip") != nullptr)
    throw std::runtime_error ("Experiment routes require explicit vehicle elements, not flows/trips");
  std::set<std::string> ids;
  for (auto *vehicle = routes->first_node ("vehicle"); vehicle != nullptr;
       vehicle = vehicle->next_sibling ("vehicle"))
    {
      auto *attribute = vehicle->first_attribute ("id");
      if (attribute == nullptr || std::string (attribute->value ()).empty ())
        throw std::runtime_error ("Every experimental vehicle must have an ID");
      const std::string id = attribute->value ();
      if (!ids.insert (id).second)
        throw std::runtime_error ("Duplicate SUMO vehicle ID: " + id);
      config.vehicleIds.push_back (id);
      config.requestPlan[id] = {};
    }
  if (ids.empty ())
    throw std::runtime_error ("Experiment route contains no explicit vehicles");
}

void
MakeDirectories (const std::string &path)
{
  std::string prefix;
  std::istringstream stream (path);
  std::string item;
  while (std::getline (stream, item, '/'))
    {
      if (item.empty ())
        continue;
      prefix += "/" + item;
      if (mkdir (prefix.c_str (), 0755) != 0 && errno != EEXIST)
        throw std::runtime_error ("Cannot create experiment output directory: " + prefix);
      struct stat attributes;
      if (stat (prefix.c_str (), &attributes) != 0 || !S_ISDIR (attributes.st_mode))
        throw std::runtime_error ("Experiment output component is not a directory: " + prefix);
    }
}

void
RequireEmptyDirectory (const std::string &path)
{
  DIR *directory = opendir (path.c_str ());
  if (directory == nullptr)
    throw std::runtime_error ("Cannot inspect experiment output directory: " + path);
  bool nonempty = false;
  errno = 0;
  while (const auto *entry = readdir (directory))
    {
      const std::string name = entry->d_name;
      if (name != "." && name != "..")
        {
          nonempty = true;
          break;
        }
    }
  const int readError = errno;
  closedir (directory);
  if (nonempty || readError != 0)
    throw std::runtime_error ("Experiment output directory must be empty: " + path);
}

void
WriteExclusive (const std::string &path, const Json &value)
{
  const int descriptor = open (path.c_str (), O_WRONLY | O_CREAT | O_EXCL, 0644);
  if (descriptor < 0)
    throw std::runtime_error ("Cannot create fresh experiment evidence: " + path);
  const std::string text = value.dump (2) + "\n";
  size_t offset = 0;
  while (offset < text.size ())
    {
      const ssize_t written = write (descriptor, text.data () + offset, text.size () - offset);
      if (written < 0 && errno == EINTR)
        continue;
      if (written <= 0)
        {
          close (descriptor);
          throw std::runtime_error ("Cannot finish writing experiment evidence: " + path);
        }
      offset += static_cast<size_t> (written);
    }
  if (close (descriptor) != 0)
    throw std::runtime_error ("Cannot close experiment evidence: " + path);
}

} // namespace

ExperimentConfig
LoadExperimentConfig (const std::string &path, const std::string &expectedScenario)
{
  char *workingDirectory = getcwd (nullptr, 0);
  if (workingDirectory == nullptr)
    throw std::runtime_error ("Cannot determine current directory");
  const std::string cwd = workingDirectory;
  free (workingDirectory);
  ExperimentConfig result;
  result.configPath = ExistingFile (cwd, path);
  const std::string base = ParentPath (result.configPath);
  const Json data = ReadJson (result.configPath);
  if (Integer (data.at ("schema_version"), "schema_version", 1, 1) != 1)
    throw std::runtime_error ("Unsupported experiment schema");
  result.scenario = data.at ("scenario").get<std::string> ();
  if (result.scenario != expectedScenario ||
      (result.scenario != "circle" && result.scenario != "grid" && result.scenario != "spidermap"))
    throw std::runtime_error ("Experiment scenario does not match the simulator");
  result.runId = data.at ("run_id").get<std::string> ();
  if (result.runId.empty ())
    throw std::runtime_error ("Experiment run_id must not be empty");
  result.sumoConfigPath = ExistingFile (base, data.at ("sumo_config").get<std::string> ());
  result.routeFilePath = ExistingFile (base, data.at ("route_file").get<std::string> ());
  result.requestPlanPath = ExistingFile (base, data.at ("request_plan").get<std::string> ());
  result.outputDirectory = AbsolutePath (base, data.at ("output_dir").get<std::string> ());
  result.measurementStartNs = TimeNs (data.at ("measurement_start_s"), "measurement_start_s");
  result.measurementEndNs = TimeNs (data.at ("measurement_end_s"), "measurement_end_s");
  result.drainEndNs = TimeNs (data.at ("drain_end_s"), "drain_end_s");
  if (result.measurementEndNs <= result.measurementStartNs ||
      result.drainEndNs < result.measurementEndNs ||
      result.drainEndNs - result.measurementEndNs < 3000000000ULL)
    throw std::runtime_error ("Experiment requires a positive measurement window and a three-second drain");
  const Json &seeds = data.at ("seeds");
  // RngStream rejects seeds at or above the smaller MRG32k3a modulus.
  result.rngSeed = Integer (seeds.at ("rng_seed"), "rng_seed", 1, 4294944442ULL);
  result.rngRun = Integer (seeds.at ("rng_run"), "rng_run", 1);
  result.sumoSeed = Integer (seeds.at ("sumo_seed"), "sumo_seed", 1, 0x7fffffffULL);
  result.srandSeed = Integer (seeds.at ("srand_seed"), "srand_seed", 1, 0xffffffffULL);
  CheckSumoRoute (result);
  ReadVehicles (result);
  const Json plan = ReadJson (result.requestPlanPath);
  Integer (plan.at ("schema_version"), "request schema_version", 1, 1);
  if (!plan.at ("requests").is_array () || plan.at ("requests").empty ())
    throw std::runtime_error ("Experiment request plan must be a nonempty array");
  std::set<std::pair<std::string, uint64_t>> keys;
  for (const Json &request : plan.at ("requests"))
    {
      const std::string vehicle = request.at ("vehicle_id").get<std::string> ();
      auto found = result.requestPlan.find (vehicle);
      if (found == result.requestPlan.end ())
        throw std::runtime_error ("Request references an unknown vehicle: " + vehicle);
      ExperimentRequest item;
      item.sequence = Integer (request.at ("sequence"), "sequence", 1);
      item.sendTimeNs = Integer (request.at ("send_time_ns"), "send_time_ns", 0,
                                std::numeric_limits<int64_t>::max ());
      if (item.sendTimeNs < result.measurementStartNs ||
          item.sendTimeNs >= result.measurementEndNs)
        throw std::runtime_error ("Request is outside the half-open measurement window");
      if (!keys.insert ({vehicle, item.sequence}).second)
        throw std::runtime_error ("Request plan contains a duplicate vehicle/sequence");
      found->second.push_back (item);
    }
  for (auto &entry : result.requestPlan)
    std::sort (entry.second.begin (), entry.second.end (),
               [] (const ExperimentRequest &first, const ExperimentRequest &second) {
                 return first.sendTimeNs == second.sendTimeNs
                            ? first.sequence < second.sequence
                            : first.sendTimeNs < second.sendTimeNs;
               });
  return result;
}

void
SaveEffectiveExperimentConfig (const ExperimentConfig &config, uint32_t strategy)
{
  if (strategy > 3)
    throw std::runtime_error ("Experiment strategy must be between zero and three");
  MakeDirectories (config.outputDirectory);
  RequireEmptyDirectory (config.outputDirectory);
  uint64_t count = 0;
  for (const auto &entry : config.requestPlan)
    count += entry.second.size ();
  WriteExclusive (config.outputDirectory + "/effective-experiment-config.json",
                  {{"schema_version", 1}, {"run_id", config.runId},
                   {"scenario", config.scenario}, {"sumo_config", config.sumoConfigPath},
                   {"route_file", config.routeFilePath}, {"request_plan", config.requestPlanPath},
                   {"output_dir", config.outputDirectory},
                   {"measurement_start_ns", config.measurementStartNs},
                   {"measurement_end_ns", config.measurementEndNs}, {"drain_end_ns", config.drainEndNs},
                   {"seeds", {{"rng_seed", config.rngSeed}, {"rng_run", config.rngRun},
                              {"sumo_seed", config.sumoSeed}, {"srand_seed", config.srandSeed}}},
                   {"strategy", strategy}, {"vehicle_ids", config.vehicleIds},
                   {"expected_requests", count}});
  MakeDirectories (config.outputDirectory + "/ai-training");
}

void
SaveExperimentCompletion (const ExperimentConfig &config, bool complete,
                          uint64_t simulatedEndNs)
{
  WriteExclusive (config.outputDirectory + "/simulation-result.json",
                  {{"schema_version", 1}, {"run_id", config.runId}, {"scenario", config.scenario},
                   {"complete", complete && simulatedEndNs >= config.drainEndNs},
                   {"simulated_end_ns", simulatedEndNs}, {"expected_end_ns", config.drainEndNs}});
}

std::string
QuoteSumoConfigPath (const std::string &path)
{
  std::string quoted = "'";
  for (const char character : path)
    quoted += character == '\'' ? "'\\''" : std::string (1, character);
  return quoted + "'";
}

} // namespace vanet
